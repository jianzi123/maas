import {createServer} from "../../console/node_modules/vite/dist/node/index.js";
import {chromium} from "../../console/node_modules/playwright-core/index.mjs";
import {mkdir,writeFile} from "node:fs/promises";
import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
const out="artifacts/qa-ui16/independent";
await mkdir(out,{recursive:true});
const checks=[],metrics=[],errors=[],focusTrace=[];
let server,browser,page,failure;
const nav=async(name)=>{await page.getByRole("navigation",{name:"主导航"}).getByRole("button",{name,exact:true}).click();await page.getByRole("heading",{name,exact:true}).waitFor();};
try{
 server=await createServer({server:{host:"127.0.0.1",port:0},define:{"import.meta.env.VITE_CONSOLE_FIXTURES":JSON.stringify("true")}});
 await server.listen();
 browser=await chromium.launch({executablePath:process.env.EDGE_PATH||"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",headless:true});
 page=await browser.newPage({viewport:{width:1440,height:900},deviceScaleFactor:1});
 page.on("pageerror",e=>errors.push(e.message));
 await page.goto("http://127.0.0.1:"+server.httpServer.address().port);
 await page.locator(".model-card").first().waitFor();
 for(const width of [1440,768,390]){
  await page.setViewportSize({width,height:width===390?844:900});
  for(const name of ["模型目录","在线试用","模型发布","请求与用量","平台 Key"]){
   await nav(name);
   const metric=await page.evaluate(()=>{
    const r=document.querySelector("h1").getBoundingClientRect();
    return {scrollX,innerWidth,documentWidth:document.documentElement.scrollWidth,heading:{x:r.x,right:r.right},brand:document.querySelector(".brand").getBoundingClientRect().toJSON()};
   });
   metrics.push({width,page:name,...metric});
   assert(metric.heading.x>=-1 && metric.heading.right<=width+1,name+" heading clipped at "+width);
  }
 }
 await nav("模型目录");
 const opener=page.getByRole("button",{name:"查看详情",exact:true}).first();await opener.click();
 const dialog=page.getByRole("dialog");await dialog.waitFor();
 for(let i=0;i<12;i++){await page.keyboard.press(i<6?"Tab":"Shift+Tab");const f=await dialog.evaluate(d=>({inside:d.contains(document.activeElement),tag:document.activeElement?.tagName,modal:d.matches(":modal"),name:document.activeElement?.getAttribute("aria-label"),documentFocused:document.hasFocus()}));focusTrace.push({i,...f});if(!f.inside){assert(f.tag==="BODY"&&f.modal&&!f.documentFocused,"interactive focus escaped dialog");await page.getByRole("navigation",{name:"主导航"}).getByRole("button").first().evaluate(el=>el.focus());assert(await dialog.evaluate(d=>d.contains(document.activeElement)||document.activeElement===document.body),"modal background accepted focus");}}
 const dialogRect=await dialog.boundingBox();assert(dialogRect.x>=-1&&dialogRect.x+dialogRect.width<=391,"drawer clipped");
 checks.push("390px model drawer is within viewport; forward/backward Tab remains modal");
 await page.screenshot({path:out+"/model-drawer-390.png"});
 await page.keyboard.press("Escape");assert.equal(await dialog.count(),0);
 assert(await opener.evaluate(el=>el===document.activeElement));checks.push("model drawer Escape restores exact opener");
 await nav("请求与用量");
 await page.getByRole("button",{name:"请求详情",exact:true}).first().click();
 await page.getByRole("dialog").waitFor();
 await page.screenshot({path:out+"/request-drawer-390.png"});
 await page.keyboard.press("Escape");assert.equal(await page.getByRole("dialog").count(),0);
 checks.push("390px request drawer opens and closes with Escape");
 await nav("模型发布");
 await page.getByRole("button",{name:"新建私有推理 CR",exact:true}).click();
 await page.getByRole("button",{name:"2 模型来源",exact:true}).click();
 const inputs=page.locator(".release-fields input");
 for(let i=0;i<await inputs.count();i++){const r=await inputs.nth(i).boundingBox();assert(r.x>=-1&&r.x+r.width<=391,"private form field clipped");}
 await page.screenshot({path:out+"/private-form-390.png",fullPage:true});
 checks.push("390px full private source form fields remain horizontally usable");
 assert.deepEqual(errors,[]);
}catch(e){failure=e.stack;if(page)await page.screenshot({path:out+"/failure.png",fullPage:true}).catch(()=>{});throw e;}
finally{await writeFile(out+"/results.json",JSON.stringify({candidate:execFileSync("git",["rev-parse","HEAD"],{encoding:"utf8"}).trim(),checks,metrics,focusTrace,errors,failure:failure??null},null,2));await browser?.close();await server?.close();}
console.log(JSON.stringify({checks:checks.length,layoutSamples:metrics.length,errors:errors.length}));