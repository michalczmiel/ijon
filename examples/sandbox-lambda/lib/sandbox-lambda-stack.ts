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
      sortKey: { name: "SK", type: dynamodb.AttributeType.STRING },
    });

    const agentRunnerFunction = new lambda.Function(this, "AgentRunner", {
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: "handler.handler",
      code: lambda.Code.fromAsset(
        path.join(import.meta.dirname, "../src/agent-runner"),
      ),
      // the agent loop is slow, the 3s default would kill it mid-iteration
      timeout: cdk.Duration.minutes(5),
      // sam local invoke can only override variables the template declares, so the
      // local-only ones are declared here as empty and filled in by env.local.json
      environment: {
        AGENT_SESSION_TABLE_NAME: agentSessionTable.tableName,
        AWS_ENDPOINT_URL_DYNAMODB: "",
        OPENAI_BASE_URL: process.env.OPENAI_BASE_URL ?? "",
        OPENAI_API_KEY: process.env.OPENAI_API_KEY ?? "",
      },
    });

    agentSessionTable.grantWriteData(agentRunnerFunction);

    const url = agentRunnerFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
    });

    new cdk.CfnOutput(this, "AgentRunnerUrl", { value: url.url });
  }
}
