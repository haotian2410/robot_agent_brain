// Requires the Codex spreadsheet runtime (@oai/artifact-tool).
import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const root=path.resolve(process.argv[2] || 'var/context-recovery-audit/20261119');
const report=JSON.parse(await fs.readFile(path.join(root,'report.json'),'utf8'));
const wb=Workbook.create();
const overview=wb.worksheets.add('最终概览');
const summary=wb.worksheets.add('用例验收'), detail=wb.worksheets.add('逐轮截图与结果');
const json=async p=>JSON.parse(await fs.readFile(p,'utf8'));
const short=x=>typeof x==='string'?x:JSON.stringify(x??'');
const link=(p,label)=>`=HYPERLINK("${p.replaceAll('"','""')}","${label}")`;
for(const s of [summary,detail]) {s.showGridLines=false;s.freezePanes.freezeRows(1);}
const latest=report.latest_cases || Object.values(Object.fromEntries(report.cases.map(c=>[c.case,c])));
overview.showGridLines=false;overview.freezePanes.freezeRows(1);
overview.getRange(`A1:F${latest.length+1}`).values=[['用例','验收预期','首次结果','最新结果','累计组数','最新证据'],...latest.map(c=>[c.case,c.expected,report.cases.find(x=>x.run==='first'&&x.case===c.case)?.passed?'通过':'未通过',c.passed?(c.case==='C05'?'合理澄清（探索项）':'通过'):'未通过',report.cases.filter(x=>x.case===c.case).length,''])];
overview.getRange(`A1:F${latest.length+1}`).format={font:{name:'Arial',size:11},wrapText:true,verticalAlignment:'center',rowHeight:48};
[12,74,18,26,14,22].forEach((w,i)=>overview.getRangeByIndexes(0,i,latest.length+1,1).format.columnWidth=w);
latest.forEach((c,i)=>{overview.getRange(`F${i+2}`).formulas=[[link(c.evidence,'打开最新证据')]];overview.getRange(`D${i+2}`).format.fill=c.passed?'#E7F3EB':'#FDE8E7';});
let nr=latest.length+4;
for(const note of ['仅验证规划和上下文，所有机器人任务 executed=false；不代表实际执行通过。',...(report.known_limits||[])]){
 overview.getRange(`A${nr}:F${nr}`).merge();overview.getRange(`A${nr}`).values=[[note]];
 overview.getRange(`A${nr}:F${nr}`).format={wrapText:true,rowHeight:45,font:{name:'Arial',size:10,color:'#52606D'}};nr++;
}
const heads=['用户指令','真实浏览器场景截图','系统返回的任务结果','批次 / 用例 / 次数','轮次 / task ID','Session ID','预期检查 / 组结果','失败链 / 次数','SemanticDraft / 修订证据','步骤台账','U/R/S/D 调用','Scene 四元组 / digest','Commands','证据目录'];
detail.getRange(`A1:N${report.turns.length+1}`).values=[heads,...report.turns.map(()=>Array(14).fill(''))];
detail.getRange(`A1:N${report.turns.length+1}`).format={font:{name:'Arial',size:10},verticalAlignment:'top',wrapText:true,rowHeight:150};
const widths=[40,37,58,24,18,36,46,36,56,48,38,58,20,22];
widths.forEach((w,i)=>detail.getRangeByIndexes(0,i,report.turns.length+1,1).format.columnWidth=w);
for(const [i,row] of report.turns.entries()) {
 const e=row.evidence, result=await json(path.join(e,'task_result.json'));
 const state=await json(path.join(e,'session_after.json'));
 const c=report.cases.find(c=>c.run===row.run&&c.case===row.case&&c.repeat===row.repeat);
 const memory=state.conversation_memory||{},chain=memory.active_failure_chain;
 const calls=result.metrics?.model_call_details||[];
 const recoveryRoot=path.join(e,'brain_evidence','conversation','recovery');
 const recoveries=[];
 for(const f of await fs.readdir(recoveryRoot).catch(()=>[])){
  const r=await json(path.join(recoveryRoot,f));
  if(r.client_request_id===row.client_request_id)recoveries.push(...r.model_calls);
 }
 const line=[row.instruction,row.capture?.status==='captured'?'':'截图阻塞：'+short(row.capture),
  `${row.outcome}; executed=${row.executed}\n${short(row.reply)}\n${short(row.error)}`,
  `${row.run} / ${row.case} / ${row.repeat}`,`${row.turn} / ${row.task_id}`,row.session_id,
  c.expected+'\n'+Object.entries(c.checks).map(([k,v])=>`${v?'✓':'✗'} ${k}`).join('\n'),
  short(result.conversation),short(chain?.semantic_draft ?? '无活动草稿；历史见证据'),
  short(chain?.step_ledger ?? state.pending_step_ledger ?? []),
  [...recoveries,...calls].map(c=>`${c.stage}: ${c.prompt_tokens??'?'}→${c.completion_tokens??'?'} tokens, ${c.elapsed_seconds??'?'}s`).join('\n')+'\n'+(recoveries.length?'R 原始响应已保存。':'早期 R 未逐次落盘或本轮无 R；见对话历史，不估算调用。'),
  short(row.scene_identity),'',''];
 // Excel limits individual strings to 32767 characters; full evidence remains on disk.
 detail.getRange(`A${i+2}:N${i+2}`).values=[line.map(v=>String(v).slice(0,30000))];
 detail.getRange(`N${i+2}`).formulas=[[link(e,'打开本轮证据')]];
 const commands=path.join(e,'artifacts','commands.json');
 if(await fs.stat(commands).catch(()=>null))detail.getRange(`M${i+2}`).formulas=[[link(commands,'Commands（未执行）')]];
 if(row.capture?.status==='captured'){
  const image=await fs.readFile(path.join(e,'screenshot.png'));
  detail.images.add({dataUrl:`data:image/png;base64,${image.toString('base64')}`,anchor:{from:{row:i+1,col:1},extent:{widthPx:240,heightPx:180}}});
 }
 detail.getRange(`G${i+2}`).format.fill=c.passed?'#E7F3EB':'#FDE8E7';
}
const sh=['批次','用例','重复','验收','未通过检查','Session','证据目录'];
summary.getRange(`A1:G${report.cases.length+1}`).values=[sh,...report.cases.map(c=>[c.run,c.case,c.repeat,c.classification || (c.passed?'通过':'未通过'),Object.entries(c.checks).filter(([,v])=>!v).map(([k])=>k).join('; '),c.session,''])];
summary.getRange(`A1:G${report.cases.length+1}`).format={font:{name:'Arial',size:11},verticalAlignment:'center',wrapText:true,rowHeight:48};
[20,12,10,23,68,40,25].forEach((w,i)=>summary.getRangeByIndexes(0,i,report.cases.length+1,1).format.columnWidth=w);
report.cases.forEach((c,i)=>{summary.getRange(`G${i+2}`).formulas=[[link(c.evidence,'打开用例证据')]];summary.getRange(`D${i+2}`).format.fill=c.passed?'#E7F3EB':'#FDE8E7';});
const note=report.cases.length+4;
summary.getRange(`A${note}:G${note}`).merge();summary.getRange(`A${note}`).values=[['仅验证规划和上下文；所有机器人结果 executed=false，未调用控制端。首次失败不会被复测覆盖。']];
summary.getRange(`A${note+1}:G${note+1}`).merge();summary.getRange(`A${note+1}`).values=[['first=首次；fixed=第一批修复；final=第二批修复；proof=最新代码与完整R审计。截图为本轮真实浏览器渲染。']];
for(const [s,end] of [[overview,'F'],[summary,'G'],[detail,'N']])s.getRange(`A1:${end}1`).format={fill:'#17365D',font:{color:'#FFFFFF',bold:true},rowHeight:35,wrapText:true};
wb.recalculate();
const inspection=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?',options:{useRegex:true,maxResults:30}});
await fs.writeFile(path.join(root,'excel_inspection.json'),JSON.stringify(inspection,null,2));
for(const [s,range,name] of [[overview,'A1:E9','overview-preview.png'],[summary,'A1:E9','summary-preview.png'],[detail,'A1:C4','turns-preview.png']]){
 const png=await wb.render({sheetName:s.name,range,scale:1,format:'png'});
 await fs.writeFile(path.join(root,name),new Uint8Array(await png.arrayBuffer()));
}
await(await SpreadsheetFile.exportXlsx(wb)).save(path.join(root,'context_recovery_results.xlsx'));
console.log(JSON.stringify({cases:report.cases.length,turns:report.turns.length,output:path.join(root,'context_recovery_results.xlsx')}));
