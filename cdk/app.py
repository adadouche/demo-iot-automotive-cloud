#!/usr/bin/env python3
import os
import aws_cdk as cdk

import biga.stacks as stacks

vision_data_s3_path = "/vCar/vision-data-event-one-sample/processed-data/"

env = cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"), region=os.getenv("CDK_DEFAULT_REGION")
)

app = cdk.App()

# Stack needed for Biga Vision Data.
bigaDataStack = stacks.BigaDataStack(
    app,
    "biga-vision-data",
    s3_path=vision_data_s3_path,
    env=env,
)

# Stack needed for Biga Vision API.
bigaAPIStack = stacks.BigaAPIStack(
    app,
    "biga-vision-api",
    bucket_name=bigaDataStack.bucket.bucket_name,
    env=env,
)

# Stack needed for Biga Vision Observability.
bigaObservabilityStack = stacks.BigaObservabilityStack(
    app,
    "biga-vision-observability",
    data_bucket=bigaDataStack.bucket,
    env=env,
)

# Stack needed for Biga FleetWise setup.
bigaFleetWiseStack = stacks.BigaFleetWiseStack(
    app,
    "biga-fleetwise",
    vision_data_bucket=bigaDataStack.bucket,
    env=env,
)

# List of repository names :
# repository_names = [
#  "fleetwise_edge_connector",
#  "rosbag2_play",
#  "can_data_analyzer_publisher",
#  "rtos_app_data_publisher",
#  "rtos_os_data_publisher",
#  "greengrass_stats_publisher",
#  "virtual_can_forwarder",
#  "ipcf_shared_memory",
#  "ipcf_shared_memory_replacement"
# ]

# List of repository names, and if they need to use graviton for building
repository_builds = [
    {"repository_name": "fleetwise_edge_connector", "use_graviton": True},
    {"repository_name": "rosbag2_play", "use_graviton": False},
    {"repository_name": "ipcf_shared_memory_replacement", "use_graviton": True},
    {"repository_name": "greengrass_stats_publisher", "use_graviton": False},
    {"repository_name": "can_data_analyzer_publisher", "use_graviton": True},
]

# Create stacks for each repository
for repo in repository_builds:
    stacks.Ggv2PipelineStack(
        app,
        f"biga-greengrass-components-pipeline-{repo['repository_name'].replace('_', '-')}",
        repository_name=repo["repository_name"],
        s3_gg_components_prefix="gg",
        use_graviton=repo["use_graviton"],
        env=env,
    )

app.synth()
