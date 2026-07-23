import { expect, test } from "vitest";
import * as cdk from "aws-cdk-lib/core";
import { Match, Template } from "aws-cdk-lib/assertions";
import { SandboxLambdaStack } from "../lib/sandbox-lambda-stack.ts";

function synth(): Template {
  const app = new cdk.App();
  const stack = new SandboxLambdaStack(app, "TestStack");
  return Template.fromStack(stack);
}

// Actions grantWriteData must never hand out. Asserting on the absence of these
// rather than the exact allowed set, which CDK adjusts between versions.
const READ_ACTIONS = [
  "dynamodb:GetItem",
  "dynamodb:BatchGetItem",
  "dynamodb:Query",
  "dynamodb:Scan",
  "dynamodb:ConditionCheckItem",
];

test("AgentRunner cannot read from the session table", () => {
  const policies = synth().findResources("AWS::IAM::Policy");

  const actions = Object.values(policies).flatMap((policy) =>
    policy.Properties.PolicyDocument.Statement.flatMap(
      (statement: { Action: string | string[] }) => statement.Action,
    ),
  );

  expect(actions).toEqual(expect.arrayContaining(["dynamodb:PutItem"]));
  expect(actions).not.toEqual(expect.arrayContaining(READ_ACTIONS));
});

test("AgentRunner function URL is public", () => {
  synth().hasResourceProperties("AWS::Lambda::Url", {
    AuthType: "NONE",
    TargetFunctionArn: Match.anyValue(),
  });
});
