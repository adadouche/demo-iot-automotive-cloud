import os

import aws_cdk as cdk

import aws_cdk.aws_s3 as s3
import aws_cdk.aws_iam as iam
import aws_cdk.aws_codepipeline as codepipeline
import aws_cdk.aws_codebuild as codebuild
import aws_cdk.aws_codepipeline_actions as pipeline_actions
import aws_cdk.aws_codecommit as codecommit

from constructs import Construct


class Ggv2PipelineStack(cdk.Stack):

    def __init__(
        self,
        scope: Construct,
        id: str,
        s3_gg_components_prefix: str,
        repository_name: str,
        use_graviton,
        **kwargs,
    ) -> None:
        super().__init__(scope, id, **kwargs)

        # Fetch and check the existence of the required environment variables
        YOCTO_SDK_S3_BUCKET = os.getenv("YOCTO_SDK_S3_BUCKET")
        if YOCTO_SDK_S3_BUCKET is None:
            raise Exception(
                "Environment variable 'YOCTO_SDK_S3_BUCKET' is not set. Please export YOCTO_SDK_S3_BUCKET!"
            )

        YOCTO_SDK_SCRIPT_NAME = os.getenv("YOCTO_SDK_SCRIPT_NAME")
        if YOCTO_SDK_SCRIPT_NAME is None:
            raise Exception(
                "Environment variable 'YOCTO_SDK_SCRIPT_NAME' is not set. Please export YOCTO_SDK_SCRIPT_NAME!"
            )

        FWE_BUILD_ARTIFACTS_BUCKET = os.getenv("FWE_BUILD_ARTIFACTS_BUCKET")
        if FWE_BUILD_ARTIFACTS_BUCKET is None:
            raise Exception(
                "Environment variable 'FWE_BUILD_ARTIFACTS_BUCKET' is not set. Please export FWE_BUILD_ARTIFACTS_BUCKET!"
            )

        # CodeCommit repository is created
        branch = "main"

        repository = codecommit.Repository(
            self,
            "Repository",
            repository_name=repository_name,
            code=codecommit.Code.from_directory(
                os.path.join(os.getcwd(), "../config/greengrass", repository_name),
                branch,
            ),
        )

        pipeline = codepipeline.Pipeline(
            self,
            "Pipeline",
            pipeline_type=codepipeline.PipelineType.V1,
        )

        # add a stage
        source_stage = pipeline.add_stage(stage_name="Source")

        # add a source action to the stage
        source_stage.add_action(
            pipeline_actions.CodeCommitSourceAction(
                action_name="Source",
                output=codepipeline.Artifact(artifact_name="SourceArtifact"),
                repository=repository,
                branch=branch,
            )
        )

        s3_gg_component_name = (
            f"{s3_gg_components_prefix}-{repository_name.replace('_', '-')}"
        )

        project = codebuild.Project(
            self,
            "Project",
            build_spec=codebuild.BuildSpec.from_source_filename("buildspec.yml"),
            source=codebuild.Source.code_commit(repository=repository),
            environment=codebuild.BuildEnvironment(
                compute_type=codebuild.ComputeType.LARGE,
                build_image=codebuild.LinuxBuildImage.from_docker_registry(
                    "public.ecr.aws/ubuntu/ubuntu:20.04_edge"
                ),
                privileged=True,  # Granting elevated privileges required to use Docker
            ),
            environment_variables={
                "COMPONENT_NAME": codebuild.BuildEnvironmentVariable(
                    value=repository_name
                ),
                "S3_GG_COMPONENT_NAME": codebuild.BuildEnvironmentVariable(
                    value=s3_gg_component_name
                ),
                "S3_FWE_ARTIFACTS": codebuild.BuildEnvironmentVariable(
                    value=f"s3://{FWE_BUILD_ARTIFACTS_BUCKET}"
                ),
                "YOCTO_SDK_S3_PATH": codebuild.BuildEnvironmentVariable(
                    value=f"s3://{YOCTO_SDK_S3_BUCKET}"
                ),
                "YOCTO_SDK_SCRIPT_NAME": codebuild.BuildEnvironmentVariable(
                    value=f"{YOCTO_SDK_SCRIPT_NAME}"
                ),
            },
        )

        if use_graviton:
            # Adding overrides for ARM64
            project.node.default_child.add_override(
                "Properties.Environment.Type", "ARM_CONTAINER"
            )
            project.node.default_child.add_override(
                "Properties.Environment.ComputeType", "BUILD_GENERAL1_LARGE"
            )

        project.role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                resources=[
                    f"arn:aws:s3:::{s3_gg_components_prefix}*",
                    f"arn:aws:s3:::{YOCTO_SDK_S3_BUCKET}*",
                    f"arn:aws:s3:::{FWE_BUILD_ARTIFACTS_BUCKET}*",
                ],
                actions=[
                    "s3:CreateBucket",
                    "s3:PutObject",
                    "s3:GetObject",
                    "s3:GetBucketLocation",
                ],
            )
        )

        project.role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                resources=["*"],
                actions=[
                    "greengrass:CreateComponentVersion",
                    "greengrass:ListComponentVersions",
                    "greengrass:CreateDeployment",
                    "iot:DescribeThing",
                    "iot:UpdateThingShadow",
                    "iot:DescribeThingGroup",
                    "iot:DescribeJob",
                    "iot:CreateJob",
                    "iot:CancelJob",
                    "kms:Decrypt",
                ],
            )
        )

        # add a stage
        build_stage = pipeline.add_stage(stage_name="Build")

        # add a source action to the stage
        build_stage.add_action(
            pipeline_actions.CodeBuildAction(
                action_name="Build",
                input=codepipeline.Artifact(artifact_name="SourceArtifact"),
                project=project,
            )
        )
