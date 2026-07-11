import * as path from "path";
import * as cdk from "aws-cdk-lib/core";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";

import { Construct } from "constructs";

export class SandboxLambdaStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const agentSessionTable = new dynamodb.Table(this, "AgentSession", {
      partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
    });

    const agentRunnerFunction = new lambda.Function(this, "AgentRunner", {
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: "handler.handler",
      code: lambda.Code.fromAsset(path.join(__dirname, "../src/agent-runner")),
      environment: {
        AGENT_SESSION_TABLE_NAME: agentSessionTable.tableName,
      },
    });

    agentSessionTable.grantWriteData(agentRunnerFunction);

    const url = agentRunnerFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
    });

    new cdk.CfnOutput(this, "AgentRunnerUrl", { value: url.url });
  }
}
