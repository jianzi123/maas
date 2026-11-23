import fs from "node:fs/promises";
import openapiTS, { astToString } from "openapi-typescript";
import prettier from "prettier";
const schema = JSON.parse(
  await fs.readFile("contracts/ar1-openapi.json", "utf8"),
);
await fs.writeFile(
  "src/chat/ar1-schema.ts",
  await prettier.format(astToString(await openapiTS(schema)), {
    parser: "typescript",
  }),
);
