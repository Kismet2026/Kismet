import os
import aws_cdk as cdk

from stacks.shared_stack import SharedStack
from stacks.domain4_stack import Domain4Stack
from stacks.domain6_stack import Domain6Stack

# TODO: Other domain owners — uncomment and add your stack file when ready
from stacks.domain1_stack import Domain1Stack
from stacks.domain2_stack import Domain2Stack
# from stacks.domain3_stack import Domain3Stack
# from stacks.domain5_stack import Domain5Stack

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_ACCOUNT", os.environ.get("AWS_ACCOUNT_ID")),
    region=os.environ.get("CDK_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1")),
)

shared = SharedStack(app, "KismetShared", env=env)

Domain6Stack(app, "KismetDomain6", shared=shared, env=env)
Domain4Stack(app, "KismetDomain4", shared=shared, env=env)

# TODO: Other domain owners — uncomment when your stack is ready
Domain1Stack(app, "KismetDomain1", shared=shared, env=env)
Domain2Stack(app, "KismetDomain2", shared=shared, env=env)
# Domain3Stack(app, "KismetDomain3", shared=shared, env=env)
# Domain5Stack(app, "KismetDomain5", shared=shared, env=env)

app.synth()
