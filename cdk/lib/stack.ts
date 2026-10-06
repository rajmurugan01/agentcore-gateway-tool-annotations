import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';

export class AnnotationsStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const pool = new cognito.UserPool(this, 'Pool', {
      selfSignUpEnabled: false, signInAliases: { username: true }, removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    const client = pool.addClient('DemoClient', { authFlows: { adminUserPassword: true }, generateSecret: false });

    // The two tools sit behind one Lambda target. Note the tool definitions below have no `annotations` field:
    // the ToolDefinition type does not offer one.
    const tools = new lambda.Function(this, 'Tools', {
      runtime: lambda.Runtime.PYTHON_3_13, handler: 'tools.handler',
      code: lambda.Code.fromAsset('../lambda'), timeout: cdk.Duration.seconds(10),
    });
    // The response interceptor. MODE is flipped by the demo to observe failure behaviour.
    const annotate = new lambda.Function(this, 'Annotate', {
      runtime: lambda.Runtime.PYTHON_3_13, handler: 'annotate.handler',
      code: lambda.Code.fromAsset('../lambda'), timeout: cdk.Duration.seconds(10),
      environment: { MODE: 'normal' },
    });

    const gwRole = new iam.Role(this, 'GatewayRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com', {
        conditions: {
          StringEquals: { 'aws:SourceAccount': this.account },
          ArnLike: { 'aws:SourceArn': `arn:aws:bedrock-agentcore:${this.region}:${this.account}:*` },
        },
      }),
    });
    tools.grantInvoke(gwRole);
    annotate.grantInvoke(gwRole);

    const authorizer = {
      customJwtAuthorizer: {
        discoveryUrl: `https://cognito-idp.${this.region}.amazonaws.com/${pool.userPoolId}/.well-known/openid-configuration`,
        allowedClients: [client.userPoolClientId],
      },
    };
    const toolSchema: agentcore.CfnGatewayTarget.ToolSchemaProperty = {
      inlinePayload: [
        {
          name: 'read_file', description: 'Read a file from a repository',
          inputSchema: { type: 'object', properties: { path: { type: 'string', description: 'file path' } }, required: ['path'] },
        },
        {
          name: 'open_pr', description: 'Open a pull request',
          inputSchema: { type: 'object', properties: { title: { type: 'string', description: 'pull request title' } }, required: ['title'] },
        },
      ],
    };
    const targetConfiguration = { mcp: { lambda: { lambdaArn: tools.functionArn, toolSchema } } };
    const creds = [{ credentialProviderType: 'GATEWAY_IAM_ROLE' }];
    const rolePolicy = gwRole.node.findChild('DefaultPolicy').node.defaultChild as cdk.CfnResource;

    // Gateway A: plain. Gateway B: identical, plus a RESPONSE interceptor.
    const plain = new agentcore.CfnGateway(this, 'PlainGateway', {
      name: 'annot-plain', protocolType: 'MCP', roleArn: gwRole.roleArn,
      authorizerType: 'CUSTOM_JWT', authorizerConfiguration: authorizer,
    });
    const annotated = new agentcore.CfnGateway(this, 'AnnotatedGateway', {
      name: 'annot-intercepted', protocolType: 'MCP', roleArn: gwRole.roleArn,
      authorizerType: 'CUSTOM_JWT', authorizerConfiguration: authorizer,
      interceptorConfigurations: [{
        interceptionPoints: ['RESPONSE'],
        interceptor: { lambda: { arn: annotate.functionArn } },
        inputConfiguration: { passRequestHeaders: false },
      }],
    });
    for (const g of [plain, annotated]) g.addResourceDependency(rolePolicy);
    new agentcore.CfnGatewayTarget(this, 'PlainTarget', {
      name: 'github', gatewayIdentifier: plain.attrGatewayIdentifier,
      targetConfiguration, credentialProviderConfigurations: creds,
    });
    new agentcore.CfnGatewayTarget(this, 'AnnotatedTarget', {
      name: 'github', gatewayIdentifier: annotated.attrGatewayIdentifier,
      targetConfiguration, credentialProviderConfigurations: creds,
    });

    new cdk.CfnOutput(this, 'Region', { value: this.region });
    new cdk.CfnOutput(this, 'UserPoolId', { value: pool.userPoolId });
    new cdk.CfnOutput(this, 'ClientId', { value: client.userPoolClientId });
    new cdk.CfnOutput(this, 'PlainGatewayUrl', { value: plain.attrGatewayUrl });
    new cdk.CfnOutput(this, 'AnnotatedGatewayUrl', { value: annotated.attrGatewayUrl });
    new cdk.CfnOutput(this, 'InterceptorFunction', { value: annotate.functionName });
  }
}
