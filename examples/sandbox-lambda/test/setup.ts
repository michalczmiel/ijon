import { afterAll } from "vitest";
import { CloudAssembly } from "aws-cdk-lib/cx-api";

// Stand-in for aws-cdk-lib/testhelpers/jest-autoclean, which is jest-only.
// Each synth writes a temp cloud assembly directory; drop them after the run.
afterAll(() => CloudAssembly.cleanupTemporaryDirectories());
