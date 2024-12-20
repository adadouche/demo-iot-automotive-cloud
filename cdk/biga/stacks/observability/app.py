import os, json

import aws_cdk as cdk
import aws_cdk.aws_iam as iam
import aws_cdk.aws_iot as iot
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_timestream as ts
from aws_cdk import RemovalPolicy

from ...constructs.grafana import GrafanaConstruct


class BigaObservabilityStack(cdk.Stack):
    def __init__(
        self, scope: cdk.App, id: str, data_bucket: s3.Bucket, **kwargs
    ) -> None:
        super().__init__(scope, id, **kwargs)

        account = self.account
        region = self.region
        bucket_name = "embedded-metrics-error-" + str(account) + "-" + str(region)

        # database/table properties
        database_name = "visibility"
        table_name = "visibility"

        database = ts.CfnDatabase(
            self,
            id="ObservabilityDatabase",
            database_name=database_name,
        )

        retention_properties = {
            "MemoryStoreRetentionPeriodInHours": 96,
            "MagneticStoreRetentionPeriodInDays": 1500,
        }
        table = ts.CfnTable(
            self,
            id="ObservabilityTable",
            database_name=database_name,
            table_name=table_name,
            retention_properties=retention_properties,
        )
        table.add_dependency(database)

        # s3 bucket
        error_bucket = s3.Bucket(
            self,
            id="ObservabilityBucket",
            bucket_name=bucket_name,
            auto_delete_objects=True,
            removal_policy=RemovalPolicy.DESTROY,
            versioned=True,
        )

        # execution role
        timestream_role = iam.Role(
            self,
            id="ObservabilityTimestreamRuleActionRole",
            assumed_by=iam.ServicePrincipal("iot.amazonaws.com"),
        )
        timestream_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "timestream:DescribeEndpoints",
                ],
                resources=["*"],
            )
        )
        timestream_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "timestream:WriteRecords",
                ],
                resources=[table.attr_arn],
            )
        )

        timestream_role_arn = timestream_role.role_arn

        # error action role
        s3_error_role = iam.Role(
            self,
            id="ObservabilityS3RuleActionRole",
            assumed_by=iam.ServicePrincipal("iot.amazonaws.com"),
        )

        s3_error_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:PutObject",
                ],
                resources=[error_bucket.bucket_arn + "/*"],
            )
        )
        s3_error_role_arn = s3_error_role.role_arn

        dimenDict = [
            {"name": "name", "value": "${name}"},
            {"name": "device", "value": "${topic(4)}"},
            {"name": "gg_component", "value": "${topic(2)}"},
            {"name": "id", "value": "${id}"},
            {"name": "device_ts", "value": "${ts_device}"},
            {"name": "component_ts", "value": "${ts_component}"},
        ]
        #  , {'name':'unit','value': '${get((SELECT unit FROM general), 0).ts}'}]
        ts_action = [
            iot.CfnTopicRule.ActionProperty(
                timestream=iot.CfnTopicRule.TimestreamActionProperty(
                    database_name=database_name,
                    dimensions=dimenDict,
                    role_arn=timestream_role_arn,
                    table_name=table_name,
                )
            )
        ]
        taskDict = dimenDict.copy()
        taskDict.append(
            {"name": "rtos subtask", "value": "${TaskCurrentStatus.CurrentStatusName}"}
        )
        task_action = [
            iot.CfnTopicRule.ActionProperty(
                timestream=iot.CfnTopicRule.TimestreamActionProperty(
                    database_name=database_name,
                    dimensions=taskDict,
                    role_arn=timestream_role_arn,
                    table_name=table_name,
                )
            )
        ]

        rule_error_action = iot.CfnTopicRule.ActionProperty(
            s3=iot.CfnTopicRule.S3ActionProperty(
                bucket_name=bucket_name,
                key='${topic(2) + "-" + topic(5) +"-" +timestamp() + "-code-"+newuuid()}',
                role_arn=s3_error_role_arn,
                canned_acl="private",
            )
        )

        table_dependent_rules = []

        # rule creation from config file
        f = open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "ruleConfig.json")
        )
        rules = json.load(f)
        for i in rules:
            # configure sql statement
            sql_statement = "SELECT "
            for c, j in enumerate(i["datafields"], 1):
                sql_statement += j
                sql_statement += ".*"
                if c < len(i["datafields"]):
                    sql_statement += ", "
            sql_statement += " FROM "
            sql_statement += i["topic"]

            action = (
                ts_action
                if i["ruleName"] != "FreeRTOSApp_to_Timestream"
                else task_action
            )
            config_topic_rule = iot.CfnTopicRule(
                self,
                i["ruleId"],
                topic_rule_payload=iot.CfnTopicRule.TopicRulePayloadProperty(
                    actions=action,
                    sql=sql_statement,
                    aws_iot_sql_version=i["sqlVersion"],
                    error_action=rule_error_action,
                ),
                rule_name=i["ruleName"],
            )
            table_dependent_rules.append(config_topic_rule)
        f.close()

        # Greengrass telemetry rules
        ts_action_ggTelemetry = [
            iot.CfnTopicRule.ActionProperty(
                timestream=iot.CfnTopicRule.TimestreamActionProperty(
                    database_name=database_name,
                    dimensions=[
                        {"name": "name", "value": "ggTelemetry"},
                        {"name": "device", "value": "${topic(4)}"},
                        {"name": "gg_component", "value": "${topic(2)}"},
                        {"name": "id", "value": "need-id"},
                        {
                            "name": "component_ts",
                            "value": "${get((SELECT TS FROM *), 0).TS}",
                        },
                    ],
                    role_arn=timestream_role_arn,
                    table_name=table_name,
                )
            )
        ]

        cfn_topic_rule_ggTelemetry = iot.CfnTopicRule(
            self,
            id="observability-topic-rule-ggtelemetry",
            topic_rule_payload=iot.CfnTopicRule.TopicRulePayloadProperty(
                actions=ts_action_ggTelemetry,
                sql="SELECT {'CpuUsage': cast((get((SELECT V FROM * WHERE N='CpuUsage'), 0).V) AS double) + 1e-9,\
                                        'TotalNumberOfFDs': get((SELECT V FROM * WHERE N='TotalNumberOfFDs'), 0).V,\
                                        'SystemMemUsage': get((SELECT V FROM * WHERE N='SystemMemUsage'), 0).V,\
                                        'NumberOfComponentsStarting': get((SELECT V FROM * WHERE N='NumberOfComponentsStarting'), 0).V,\
                                        'NumberOfComponentsInstalled': get((SELECT V FROM * WHERE N='NumberOfComponentsInstalled'), 0).V,\
                                        'NumberOfComponentsStateless': get((SELECT V FROM * WHERE N='NumberOfComponentsStateless'), 0).V,\
                                        'NumberOfComponentsStopping': get((SELECT V FROM * WHERE N='NumberOfComponentsStopping'), 0).V,\
                                        'NumberOfComponentsBroke': get((SELECT V FROM * WHERE N='NumberOfComponentsBroken'), 0).V,\
                                        'NumberOfComponentsRunning': get((SELECT V FROM * WHERE N='NumberOfComponentsRunning'), 0).V,\
                                        'NumberOfComponentsErrored': get((SELECT V FROM * WHERE N='NumberOfComponentsErrored'), 0).V,\
                                        'NumberOfComponentsNew': get((SELECT V FROM * WHERE N='NumberOfComponentsNew'), 0).V,\
                                        'NumberOfComponentsFinished': get((SELECT V FROM * WHERE N='NumberOfComponentsFinished'), 0).V}\
                                        FROM 'dt/+/embedded-metrics/+/gg-telemetry'",
                aws_iot_sql_version="2016-03-23",
                error_action=rule_error_action,
            ),
            rule_name="ggTelemetry_to_Timestream",
        )
        table_dependent_rules.append(cfn_topic_rule_ggTelemetry)

        for rule in table_dependent_rules:
            rule.add_dependency(table)

        GrafanaConstruct(self, "GrafanaConstruct", data_bucket)
