import * as cdk from 'aws-cdk-lib';
import { AnnotationsStack } from '../lib/stack';

const app = new cdk.App();
new AnnotationsStack(app, 'GatewayToolAnnotations', {
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.DEMO_REGION ?? 'us-east-1' },
});
