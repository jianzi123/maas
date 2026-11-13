import fs from "node:fs/promises";
import openapiTS, { astToString } from "openapi-typescript";
import prettier from "prettier";
const stable = JSON.parse(
  await fs.readFile("contracts/openapi-v0.4.json", "utf8"),
);
const patch = JSON.parse(
  await fs.readFile("contracts/j01-v04.patch.json", "utf8"),
);
const response = stable.paths["/api/admin/v1/keys"].post.responses["201"];
if (response.description !== patch[0].value)
  throw Error("J01 patch precondition failed");
response.description = patch[1].value;
for (const [schema, path] of [
  [stable, "src/api/schema.ts"],
  [
    JSON.parse(
      await fs.readFile("contracts/query-recovery-draft.json", "utf8"),
    ),
    "src/api/draft-schema.ts",
  ],
]) {
  const ast = await openapiTS(schema);
  await fs.writeFile(
    path,
    await prettier.format(astToString(ast), { parser: "typescript" }),
  );
}
console.log(
  "Generated stable + independent draft types. J01 applied in memory; original snapshots preserved.",
);
