import os

import aws_cdk as cdk
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_ecs as ecs
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_elasticloadbalancingv2 as elbv2
import aws_cdk.aws_efs as efs
import aws_cdk.aws_logs as logs
import aws_cdk.aws_iam as iam
import aws_cdk.aws_secretsmanager as secretsmanager
import aws_cdk.aws_ecs_patterns as ecs_patterns
import aws_cdk.aws_ecr_assets as ecr_assets
import aws_cdk.aws_cloudfront as cloudfront
import aws_cdk.aws_cloudfront_origins as origins

from constructs import Construct


class GrafanaConstruct(Construct):
    def __init__(self, scope: Construct, id: str, data_bucket: s3.Bucket, **kwargs):
        super().__init__(scope, id, **kwargs)

        vpc = ec2.Vpc.from_lookup(
            self,
            id="VPC",
            is_default=True,
        )

        cluster = ecs.Cluster(
            self,
            id="GrafanaECSCluster",
            vpc=vpc,
        )

        file_system = efs.FileSystem(
            self,
            id="GrafanaEfsFileSystem",
            vpc=vpc,
            encrypted=True,
            lifecycle_policy=efs.LifecyclePolicy.AFTER_14_DAYS,
            performance_mode=efs.PerformanceMode.GENERAL_PURPOSE,
            throughput_mode=efs.ThroughputMode.BURSTING,
            # WARNING: This shouldn't be used in production
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        access_point = efs.AccessPoint(
            self,
            id="GrafanaEfsAccessPoint",
            file_system=file_system,
            path="/var/lib/grafana",
            posix_user={"gid": "1000", "uid": "1000"},
            create_acl={"owner_gid": "1000", "owner_uid": "1000", "permissions": "755"},
        )

        # task log group
        log_group = logs.LogGroup(
            self,
            id="GrafanaECSTaskLogGroup",
            retention=logs.RetentionDays.ONE_MONTH,
        )

        # container log driver
        container_log_driver = ecs.LogDrivers.aws_logs(
            stream_prefix=cdk.Aws.STACK_NAME, log_group=log_group
        )

        # task Role
        grafana_ecs_task_role = iam.Role(
            self,
            id="GrafanaECSTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )

        visibility_database_arn = f"arn:aws:timestream:{cdk.Aws.REGION}:{cdk.Aws.ACCOUNT_ID}:database/visibility"
        fleetwise_database_arn = f"arn:aws:timestream:{cdk.Aws.REGION}:{cdk.Aws.ACCOUNT_ID}:database/FleetWise"
        all_tables_in_region = (
            f"arn:aws:timestream:{cdk.Aws.REGION}:{cdk.Aws.ACCOUNT_ID}:database/*"
        )

        grafana_ecs_task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "timestream:DescribeDatabase",
                    "timestream:ListTagsForResource",
                ],
                resources=[
                    visibility_database_arn,
                    fleetwise_database_arn,
                ],
            )
        )

        grafana_ecs_task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "timestream:DescribeTable",
                    "timestream:Select",
                    "timestream:ListMeasures",
                ],
                resources=[
                    all_tables_in_region,
                ],
            )
        )

        grafana_ecs_task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "timestream:ListTables",
                ],
                resources=[
                    visibility_database_arn + "/",
                    fleetwise_database_arn + "/",
                ],
            )
        )

        grafana_ecs_task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "timestream:DescribeEndpoints",
                    "timestream:SelectValues",
                    "timestream:CancelQuery",
                    "timestream:ListDatabases",
                    "timestream:DescribeScheduledQuery",
                    "timestream:ListScheduledQueries",
                    "timestream:DescribeBatchLoadTask",
                    "timestream:ListBatchLoadTasks",
                ],
                resources=["*"],
            )
        )

        grafana_ecs_task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "athena:*",
                    "glue:Get*",
                    "glue:BatchGetPartition",
                ],
                resources=["*"],
            )
        )

        grafana_ecs_task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetBucketLocation",
                    "s3:GetObject",
                    "s3:ListBucket",
                    "s3:ListBucketMultipartUploads",
                    "s3:ListMultipartUploadParts",
                    "s3:AbortMultipartUpload",
                    "s3:PutObject",
                ],
                resources=[
                    "arn:aws:s3:::aws-athena-query-results-*",
                ],
            )
        )

        grafana_ecs_task_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3:GetObject",
                    "s3:ListBucket",
                ],
                resources=[
                    "arn:aws:s3:::" + data_bucket.bucket_name + "*",
                ],
            )
        )

        # execution Role
        grafana_ecs_execution_role = iam.Role(
            self,
            id="GrafanaECSTaskExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
        )

        grafana_ecs_execution_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=[log_group.log_group_arn],
            )
        )

        # Create Task Definition
        volume_name = "efsGrafanaVolume"

        volume_config = {
            "name": volume_name,
            "efsVolumeConfiguration": {
                "fileSystemId": file_system.file_system_id,
                "transitEncryption": "ENABLED",
                "authorizationConfig": {"accessPointId": access_point.access_point_id},
            },
        }

        grafana_ecs_task_definition = ecs.FargateTaskDefinition(
            self,
            id="GrafanaECSTaskDefinition",
            task_role=grafana_ecs_task_role,
            execution_role=grafana_ecs_execution_role,
            volumes=[volume_config],
        )

        # Grafana Admin Password
        grafanaAdminPassword = secretsmanager.Secret(self, "GrafanaAdminPassword")
        # Allow Task to access Grafana Admin Password
        grafanaAdminPassword.grant_read(grafana_ecs_task_role)

        # Our Grafana image
        image = ecr_assets.DockerImageAsset(
            self,
            id="GrafanaDockerImage",
            directory=os.path.join(os.getcwd(), "../config/grafana"),
        )
        # Web Container
        container_web = grafana_ecs_task_definition.add_container(
            "web",
            image=ecs.ContainerImage.from_docker_image_asset(image),
            logging=container_log_driver,
            secrets={
                "GF_SECURITY_ADMIN_PASSWORD": ecs.Secret.from_secrets_manager(
                    grafanaAdminPassword
                )
            },
            # environment=[
            #     {"name": "variable", "value": "value"},
            # ],
        )

        # set port mapping
        container_web.add_port_mappings(ecs.PortMapping(container_port=3000))

        container_web.add_mount_points(
            ecs.MountPoint(
                source_volume=volume_config["name"],
                container_path="/var/lib/grafana",
                read_only=False,
            )
        )

        # Create a load-balanced Fargate service and make it public
        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            id="GrafanaFargateService",
            cluster=cluster,
            cpu=2048,
            desired_count=1,
            task_definition=grafana_ecs_task_definition,
            memory_limit_mib=4096,
            protocol=elbv2.ApplicationProtocol.HTTP,
            platform_version=ecs.FargatePlatformVersion.VERSION1_4,
            assign_public_ip=True,
        )

        elbv2.ApplicationListenerRule(
            self,
            id="GrafanaApplicationListenerHeaderRule",
            priority=1,
            listener=fargate_service.listener,
            action=elbv2.ListenerAction.forward(
                target_groups=[
                    fargate_service.target_group,
                ]
            ),
            conditions=[
                # elbv2.ListenerCondition.http_header("X-Custom-Header", ["biga-123"]),
                elbv2.ListenerCondition.path_patterns(["/"]),
            ],
        )

        cfn_listener = fargate_service.listener.node.default_child
        default_actions = [
            {
                "Type": "fixed-response",
                "FixedResponseConfig": {
                    "ContentType": "text/plain",
                    "MessageBody": "Access Denied.",
                    "StatusCode": "403",
                },
            },
        ]
        cfn_listener.add_property_override("DefaultActions", default_actions)

        fargate_service.task_definition.find_container("web").add_environment(
            "GF_SERVER_ROOT_URL",
            f"http://{fargate_service.load_balancer.load_balancer_dns_name}",
        )
        fargate_service.target_group.configure_health_check(path="/api/health")

        # Allow Task to access EFS
        file_system.connections.allow_default_port_from(
            fargate_service.service.connections
        )

        distribution = cloudfront.Distribution(
            self,
            id="GrafanaCloudfrontDistribution",
            comment="Cloudfront Distribution for Grafana",
            default_behavior=cloudfront.BehaviorOptions(
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                origin=origins.LoadBalancerV2Origin(
                    load_balancer=fargate_service.load_balancer,
                    custom_headers={"X-Custom-Header": "biga-123"},
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                ),
            ),
            enabled=True,
        )

        aws_get_secret = "aws secretsmanager get-secret-value --secret-id"

        cdk.CfnOutput(
            self,
            id="GrafanaAdminPasswordCLICommand",
            key="GrafanaAdminPasswordCLICommand",
            value=f"{aws_get_secret} {grafanaAdminPassword.secret_name}|jq .SecretString -r",
            description="AWS CLI command to retireve the user name and password to access Grafana",
        )

        cdk.CfnOutput(
            self,
            id="GrafanaURL",
            key="GrafanaURL",
            value=distribution.domain_name,
            description="The URL to access Grafana via Cloudfront",
        )
