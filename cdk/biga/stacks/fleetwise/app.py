import re, os, json

import aws_cdk as cdk
import aws_cdk.aws_timestream as ts
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_iam as iam
import cdk_aws_iotfleetwise as ifw

from constructs import Construct


class BigaFleetWiseStack(cdk.Stack):
    def __init__(
        self, scope: Construct, id: str, vision_data_bucket: s3.Bucket, **kwargs
    ) -> None:
        super().__init__(scope, id, **kwargs)

        database_name = "FleetWise"
        table_name = "FleetWise"
        database = ts.CfnDatabase(
            self,
            id="FleetWiseDatabase",
            database_name=database_name,
        )

        table = ts.CfnTable(
            self,
            id="FleetWiseTable",
            database_name=database_name,
            table_name=table_name,
        )

        table.node.add_dependency(database)

        role = iam.Role(
            self,
            id="FleetWiseRole",
            assumed_by=iam.ServicePrincipal("iotfleetwise.amazonaws.com"),
            inline_policies={
                "FWTimestreamAccess": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="timestreamIngestion",
                            effect=iam.Effect.ALLOW,
                            actions=[
                                "timestream:WriteRecords",
                                "timestream:Select",
                                "timestream:DescribeTable",
                            ],
                            resources=[table.attr_arn],
                        ),
                        iam.PolicyStatement(
                            sid="timestreamDescribeEndpoint",
                            effect=iam.Effect.ALLOW,
                            actions=["timestream:DescribeEndpoints"],
                            resources=["*"],
                        ),
                    ]
                ),
            },
        )

        ifw.Logging(
            self,
            id="FleetWiseLoggingDefault",
            log_group_name="AWSIotFleetWiseLogsV1",
            enable_logging="ERROR",
        )

        nodes = [
            ifw.SignalCatalogBranch(
                fully_qualified_name="Vehicle", description="Vehicle"
            )
        ]

        signals_map_model_a = {}
        with open(os.path.join(os.getcwd(), "../config/fleetwise/hscan.dbc")) as f:
            lines = f.readlines()
            for line in lines:
                found = re.search(r"^\s+SG_\s+(\w+)\s+.*", line)
                if found:
                    signal_name = found.group(1)
                    nodes.append(
                        ifw.SignalCatalogSensor(
                            fully_qualified_name=f"Vehicle.{signal_name}",
                            data_type="DOUBLE",
                        )
                    )
                    signals_map_model_a[signal_name] = f"Vehicle.{signal_name}"
        f = open(
            os.path.join(os.getcwd(), "../config/fleetwise/ros/ros2-nodes-carla.json")
        )
        data = json.load(f)

        for obj in data:
            key = list(obj.keys())[0]
            val = obj.get(key)
            if key == "sensor":
                nodes.append(
                    ifw.SignalCatalogSensor(
                        fully_qualified_name=val.get("fullyQualifiedName"),
                        data_type=val.get("dataType"),
                        struct_fully_qualified_name=val.get("structFullyQualifiedName"),
                    )
                )
            if key == "struct":
                nodes.append(
                    ifw.SignalCatalogCustomStruct(
                        fully_qualified_name=val.get("fullyQualifiedName")
                    )
                )
            if key == "property":
                nodes.append(
                    ifw.SignalCatalogCustomProperty(
                        fully_qualified_name=val.get("fullyQualifiedName"),
                        data_type=val.get("dataType"),
                        data_encoding=val.get("dataEncoding"),
                        struct_fully_qualified_name=val.get("structFullyQualifiedName"),
                    )
                )
            if key == "branch":
                nodes.append(
                    ifw.SignalCatalogBranch(
                        fully_qualified_name=val.get("fullyQualifiedName")
                    )
                )

        signal_catalog = ifw.SignalCatalog(
            self,
            id="FleetWiseSignalCatalog",
            name="FleetWiseSignalCatalog",
            description="IoT FleetWise SignalCatalog",
            nodes=nodes,
        )

        f = open(
            os.path.join(os.getcwd(), "../config/fleetwise/ros/ros2-decoders-carla.json")
        )
        decoders = json.load(f)
        array = []
        for obj in decoders:
            array.append(ifw.MessageVehicleSignal(props=obj))

        with open(os.path.join(os.getcwd(), "../config/fleetwise/hscan.dbc")) as f:
            model_a = ifw.VehicleModel(
                self,
                id="FleetWiseVehicleModel",
                signal_catalog=signal_catalog,
                name="modelA",
                description="Model A vehicle",
                network_interfaces=[
                    ifw.CanVehicleInterface(interface_id="1", name="can0"),
                    ifw.MiddlewareVehicleInterface(interface_id="10", name="ros2"),
                ],
                signals_json=array,
                network_file_definitions=[
                    ifw.CanDefinition("1", signals_map_model_a, [f.read()])
                ],
            )

        vCar = ifw.Vehicle(
            self,
            id="FleetWiseVehicle",
            vehicle_model=model_a,
            vehicle_name="vCar",
            create_iot_thing=True,
        )

        fleet = ifw.Fleet(
            self,
            id="FleetWiseFleet",
            fleet_id="fleet1",
            signal_catalog=signal_catalog,
            description="my fleet1",
            vehicles=[vCar],
        )

        prefix = f"${{VehicleName}}/vision-system-data-event"
        s3_prefix = prefix.replace("${VehicleName}", vCar.vehicle_name)
        prefix_heartbeat = f"${{VehicleName}}/vision-system-data-heartbeat"
        s3_prefix_heartbeat = prefix_heartbeat.replace(
            "${VehicleName}", vCar.vehicle_name
        )

        prefix_one_sample = f"${{VehicleName}}/vision-data-event-one-sample"
        s3_prefix_one_sample = prefix_one_sample.replace(
            "${VehicleName}", vCar.vehicle_name
        )

        can_heartbeat_campaign = ifw.Campaign(
            self,
            id="FleetWiseCampaignCANSignalsHeartBeat",
            name="FwTimeBasedCANHeartbeat",
            target=vCar,
            compression="SNAPPY",
            collection_scheme=ifw.TimeBasedCollectionScheme(cdk.Duration.seconds(10)),
            signals=[
                ifw.CampaignSignal(name="Vehicle.BrakePressure"),
                ifw.CampaignSignal(name="Vehicle.VehicleSpeed"),
                ifw.CampaignSignal(name="Vehicle.ThrottlePosition"),
                ifw.CampaignSignal(name="Vehicle.SteeringPosition"),
                ifw.CampaignSignal(name="Vehicle.BrakePressure"),
                ifw.CampaignSignal(name="Vehicle.Gear"),
                ifw.CampaignSignal(name="Vehicle.CollisionIntensity"),
                ifw.CampaignSignal(name="Vehicle.AccelerationX"),
                ifw.CampaignSignal(name="Vehicle.AccelerationY"),
                ifw.CampaignSignal(name="Vehicle.AccelerationZ"),
                ifw.CampaignSignal(name="Vehicle.GyroscopeX"),
                ifw.CampaignSignal(name="Vehicle.GyroscopeY"),
                ifw.CampaignSignal(name="Vehicle.GyroscopeZ"),
                ifw.CampaignSignal(name="Vehicle.Latitude"),
                ifw.CampaignSignal(name="Vehicle.Longitude"),
            ],
            campaign_s3arn="",
            timestream_arn=table.attr_arn,
            fw_timestream_role=role.role_arn,
            use_s3=False,
            auto_approve=True,
        )

        can_brake_event_campaign = ifw.Campaign(
            self,
            id="FleetWiseCampaignCANSignalsBrakeEvent",
            name="FwBrakeEventCANCampaign",
            compression="SNAPPY",
            target=vCar,
            post_trigger_collection_duration=1000,
            collection_scheme=ifw.ConditionBasedCollectionScheme(
                condition_language_version=1,
                expression="$variable.`Vehicle.BrakePressure` > 7000",
                minimum_trigger_interval_ms=1000,
                trigger_mode="ALWAYS",
            ),
            signals=[
                ifw.CampaignSignal(name="Vehicle.BrakePressure"),
                ifw.CampaignSignal(name="Vehicle.VehicleSpeed"),
                ifw.CampaignSignal(name="Vehicle.ThrottlePosition"),
                ifw.CampaignSignal(name="Vehicle.SteeringPosition"),
                ifw.CampaignSignal(name="Vehicle.BrakePressure"),
                ifw.CampaignSignal(name="Vehicle.Gear"),
                ifw.CampaignSignal(name="Vehicle.CollisionIntensity"),
                ifw.CampaignSignal(name="Vehicle.AccelerationX"),
                ifw.CampaignSignal(name="Vehicle.AccelerationY"),
                ifw.CampaignSignal(name="Vehicle.AccelerationZ"),
                ifw.CampaignSignal(name="Vehicle.GyroscopeX"),
                ifw.CampaignSignal(name="Vehicle.GyroscopeY"),
                ifw.CampaignSignal(name="Vehicle.GyroscopeZ"),
                ifw.CampaignSignal(name="Vehicle.Latitude"),
                ifw.CampaignSignal(name="Vehicle.Longitude"),
            ],
            campaign_s3arn="",
            timestream_arn=table.attr_arn,
            fw_timestream_role=role.role_arn,
            use_s3=False,
            auto_approve=False,
        )

        vision_data_bucket.add_to_resource_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:ListBucket",
                ],
                principals=[
                    iam.ServicePrincipal("iotfleetwise.amazonaws.com"),
                ],
                resources=[
                    vision_data_bucket.bucket_arn + "/*",
                    vision_data_bucket.bucket_arn,
                ],
            )
        )

        rich_sensor_data_heartbeat_campaign = ifw.Campaign(
            self,
            id="FleetWiseCampaignRichSensorHeartbeat",
            name="FwTimeBasedCampaignRichSensorHeartbeat",
            spooling_mode="TO_DISK",
            target=vCar,
            compression="SNAPPY",
            collection_scheme=ifw.TimeBasedCollectionScheme(cdk.Duration.seconds(30)),
            signals=[
                ifw.CampaignSignal(name="Vehicle.Cameras.Front.Image"),
                ifw.CampaignSignal(name="Vehicle.Cameras.Front.CameraInfo"),
                ifw.CampaignSignal(name="Vehicle.Cameras.DepthFront.CameraInfo"),
                ifw.CampaignSignal(name="Vehicle.Cameras.DepthFront.Image"),
                ifw.CampaignSignal(name="Vehicle.Sensors.Lidar"),
                ifw.CampaignSignal(name="Vehicle.ROS2.CollisionWith"),
                ifw.CampaignSignal(name="Vehicle.ROS2.CollisionIntensity"),
                ifw.CampaignSignal(name="Vehicle.LaneInvasion"),
                ifw.CampaignSignal(name="Vehicle.Speedometer"),
                ifw.CampaignSignal(name="Vehicle.Sensors.RadarFront"),
                ifw.CampaignSignal(name="Vehicle.Odometry"),
                ifw.CampaignSignal(name="Vehicle.GNSS"),
                ifw.CampaignSignal(name="Vehicle.ROS2.Gear"),
                ifw.CampaignSignal(name="Vehicle.ROS2.LaneCrossing"),
                ifw.CampaignSignal(name="Vehicle.ROS2.ThrottlePosition"),
                ifw.CampaignSignal(name="Vehicle.ROS2.BrakePressure"),
                ifw.CampaignSignal(name="Vehicle.imu"),
                ifw.CampaignSignal(name="Vehicle.Markers"),
            ],
            campaign_s3arn=vision_data_bucket.bucket_arn,
            prefix=s3_prefix_heartbeat,
            data_format="JSON",
            timestream_arn="",
            fw_timestream_role="",
            use_s3=True,
            auto_approve=False,
        )

        rich_sensor_data_and_can_campaign = ifw.Campaign(
            self,
            id="FleetWiseCampaignMixedSensorsBrakeEvent",
            name="FwBrakeEventMixedSensorsCampaign",
            spooling_mode="TO_DISK",
            compression="SNAPPY",
            target=vCar,
            post_trigger_collection_duration=1000,
            collection_scheme=ifw.ConditionBasedCollectionScheme(
                condition_language_version=1,
                expression="$variable.`Vehicle.BrakePressure` > 7000",
                minimum_trigger_interval_ms=1000,
                trigger_mode="ALWAYS",
            ),
            signals=[
                ifw.CampaignSignal(name="Vehicle.Cameras.Front.Image"),
                ifw.CampaignSignal(name="Vehicle.Cameras.Front.CameraInfo"),
                ifw.CampaignSignal(name="Vehicle.Cameras.DepthFront.CameraInfo"),
                ifw.CampaignSignal(name="Vehicle.Cameras.DepthFront.Image"),
                ifw.CampaignSignal(name="Vehicle.Sensors.Lidar"),
                ifw.CampaignSignal(name="Vehicle.ROS2.CollisionWith"),
                ifw.CampaignSignal(name="Vehicle.ROS2.CollisionIntensity"),
                ifw.CampaignSignal(name="Vehicle.LaneInvasion"),
                ifw.CampaignSignal(name="Vehicle.Speedometer"),
                ifw.CampaignSignal(name="Vehicle.Sensors.RadarFront"),
                ifw.CampaignSignal(name="Vehicle.Odometry"),
                ifw.CampaignSignal(name="Vehicle.GNSS"),
                ifw.CampaignSignal(name="Vehicle.ROS2.Gear"),
                ifw.CampaignSignal(name="Vehicle.ROS2.LaneCrossing"),
                ifw.CampaignSignal(name="Vehicle.ROS2.ThrottlePosition"),
                ifw.CampaignSignal(name="Vehicle.ROS2.BrakePressure"),
                ifw.CampaignSignal(name="Vehicle.imu"),
                ifw.CampaignSignal(name="Vehicle.Markers"),
                # CAN
                ifw.CampaignSignal(name="Vehicle.BrakePressure"),
                ifw.CampaignSignal(name="Vehicle.VehicleSpeed"),
                ifw.CampaignSignal(name="Vehicle.ThrottlePosition"),
                ifw.CampaignSignal(name="Vehicle.SteeringPosition"),
                ifw.CampaignSignal(name="Vehicle.BrakePressure"),
                ifw.CampaignSignal(name="Vehicle.Gear"),
                ifw.CampaignSignal(name="Vehicle.CollisionIntensity"),
                ifw.CampaignSignal(name="Vehicle.AccelerationX"),
                ifw.CampaignSignal(name="Vehicle.AccelerationY"),
                ifw.CampaignSignal(name="Vehicle.AccelerationZ"),
                ifw.CampaignSignal(name="Vehicle.GyroscopeX"),
                ifw.CampaignSignal(name="Vehicle.GyroscopeY"),
                ifw.CampaignSignal(name="Vehicle.GyroscopeZ"),
                ifw.CampaignSignal(name="Vehicle.Latitude"),
                ifw.CampaignSignal(name="Vehicle.Longitude"),
            ],
            campaign_s3arn=vision_data_bucket.bucket_arn,
            prefix=s3_prefix,
            data_format="JSON",
            timestream_arn="",
            fw_timestream_role="",
            use_s3=True,
            auto_approve=False,
        )

        rich_sensor_data_and_can_campaign_one_sample = ifw.Campaign(
            self,
            id="FleetWiseCampaignMixedSensorsBrakeEventOneSampleSize",
            name="FwBrakeEventMixedSensorsCampaignOneSampleSize",
            spooling_mode="TO_DISK",
            compression="SNAPPY",
            target=vCar,
            post_trigger_collection_duration=0,
            collection_scheme=ifw.ConditionBasedCollectionScheme(
                condition_language_version=1,
                expression="$variable.`Vehicle.BrakePressure` > 16000",
                minimum_trigger_interval_ms=1000,
                trigger_mode="RISING_EDGE",
            ),
            signals=[
                ifw.CampaignSignal(
                    name="Vehicle.Cameras.Front.Image", max_sample_count=1
                ),
                ifw.CampaignSignal(
                    name="Vehicle.Cameras.Front.CameraInfo", max_sample_count=1
                ),
                ifw.CampaignSignal(
                    name="Vehicle.Cameras.DepthFront.CameraInfo", max_sample_count=1
                ),
                ifw.CampaignSignal(
                    name="Vehicle.Cameras.DepthFront.Image", max_sample_count=1
                ),
                ifw.CampaignSignal(name="Vehicle.Sensors.Lidar", max_sample_count=1),
                ifw.CampaignSignal(
                    name="Vehicle.ROS2.CollisionWith", max_sample_count=1
                ),
                ifw.CampaignSignal(
                    name="Vehicle.ROS2.CollisionIntensity", max_sample_count=1
                ),
                ifw.CampaignSignal(name="Vehicle.LaneInvasion", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.Speedometer", max_sample_count=1),
                ifw.CampaignSignal(
                    name="Vehicle.Sensors.RadarFront", max_sample_count=1
                ),
                ifw.CampaignSignal(name="Vehicle.Odometry", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.GNSS", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.ROS2.Gear", max_sample_count=1),
                ifw.CampaignSignal(
                    name="Vehicle.ROS2.LaneCrossing", max_sample_count=1
                ),
                ifw.CampaignSignal(
                    name="Vehicle.ROS2.ThrottlePosition", max_sample_count=1
                ),
                ifw.CampaignSignal(
                    name="Vehicle.ROS2.BrakePressure", max_sample_count=1
                ),
                ifw.CampaignSignal(name="Vehicle.imu", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.Markers", max_sample_count=1),
                # CAN
                ifw.CampaignSignal(name="Vehicle.BrakePressure", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.VehicleSpeed", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.ThrottlePosition", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.SteeringPosition", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.BrakePressure", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.Gear", max_sample_count=1),
                ifw.CampaignSignal(
                    name="Vehicle.CollisionIntensity", max_sample_count=1
                ),
                ifw.CampaignSignal(name="Vehicle.AccelerationX", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.AccelerationY", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.AccelerationZ", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.GyroscopeX", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.GyroscopeY", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.GyroscopeZ", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.Latitude", max_sample_count=1),
                ifw.CampaignSignal(name="Vehicle.Longitude", max_sample_count=1),
            ],
            campaign_s3arn=vision_data_bucket.bucket_arn,
            prefix=s3_prefix_one_sample,
            data_format="JSON",
            timestream_arn="",
            fw_timestream_role="",
            use_s3=True,
            auto_approve=True,
        )
        
        cdk.CfnOutput(
            self,
            id="FleetWiseSignalCatalogOutput",
            value=signal_catalog.name,
            description="IoT FleetWise Signal Catalog name",
        )
        cdk.CfnOutput(
            self,
            id="FleetWiseVehicleModelOutput",
            value=model_a.name,
            description="IoT FleetWise Vehicle Model name",
        )
        cdk.CfnOutput(
            self,
            id="FleetWiseVehicleOutput",
            value=vCar.vehicle_name,
            description="IoT FleetWise Vehicle name",
        )
        cdk.CfnOutput(
            self,
            id="FleetWiseFleetOutput",
            value=fleet.fleet_id,
            description="IoT FleetWise Fleet name",
        )
        