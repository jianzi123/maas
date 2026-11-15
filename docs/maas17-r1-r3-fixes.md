# MAAS-17 R1–R3 有界修复

审查基线c7e863b，沿同一PR #6接续，不合并远端、不重开原#1–#4。已读取Mika首轮和专职专家补充报告；认证ZIP中的`maas17_stream_probe_test.go`逐字节保留为`internal/kernel/maas17_review_test.go`，SHA256=`4dac0037a305c2ab8bdc14491962e9ae2ec1fb7bb56994f0276489023132b0cc`。修复前正常/data-error两项通过，R1/R2/R3三项失败，见maas17-before.txt；未修改原失败oracle。

## R1

完整EOF判定不再绕过原ctx/sendCtx与硬截止复核。成功收尾前再检查，原finish写回后的取消/超时记为取消/超时，原实际用量未知、held保留、无正常DONE。stop归因继续优先sendCtx原首次终止原因，内部清理cancel不改变协议失败归因。

成功结算使用内部`finalizeChecked`，在既有完整写集完成、COMMIT发起前再核原终止状态和主库时钟/原Deadline。不新增账本或公开API；检查失败在同一sql.Tx整体rollback后，用原EventID落唯一异常终态。提交ACK未知沿原ErrCommitUnknown，不因ctx变化猜测退款或重发。最后检查与跨系统COMMIT不构成跨时钟原子承诺；检查点后的终止/提交未知必须按原耐久身份恢复，不编造结果。

已经确认提交的终态不重新结算。最终usage写回后取消时只停止正常DONE/传输，保留已提交actual19/held0和唯一终态；不能把晚取消反向改为unknown。扩展事务测试在tx内确认usage_events写集确已建立，再触发取消，验证rollback后终态0/known0/reserved140，随后仅一次cancelled终态、held140。

## R2

seenFinish成为显式展示边界。finish后任何新choice（包括新content或另一矛盾finish）在Write前拒绝，不展示AFTER_FINISH、不恢复成功。原receipt仍先耐久保存；后续choices为空或缺省的独立usage继续经批准UsagePolicy处理，不粗暴拒绝所有finish后usage、不改成last/max。final_only来源的finish后独立final正例保留。

## R3

`config/mysql/release-permissions.sql`直接为原maas_release_publisher增加完成hook所需操作元数据列SELECT及仅四列UPDATE(state,reason,publication_id,updated_at)。不授INSERT操作、不授action/spec_sha256/expected_rv写，不继承operations/core角色；原release→operation锁序和同事务hook不变，权限错误仍整笔回滚。

SELECT列为cluster_id/operation_id/cr_uid/namespace/name/requested_generation/state/acknowledged/desired_state/action/spec_sha256；UPDATE仅上述完成列。其他JOIN来自原publisher已有发布/保留快照权限。模板只在自有临时schema和随机角色上运行，未修改生产账户。

扩展测试从两份真实模板建立专用default role，检查Activate及原operation完成、撤销UPDATE(state)后CloseAdmission错误且门禁仍开放/无半提交、恢复最窄列权限后真实COMMIT丢ACK、原CommandID恢复，以及Paused cleanup/原operation完成。实际拒绝修改action/spec_sha256/expected_rv、Key、预算、usage及DDL；拒绝必须是MySQL1142/1143，不能用不存在表假装权限拒绝。

## 复现与范围

```sh
MAAS_TEST_PATTERN='^(TestMAAS17|TestR1|TestR3)' \
MAAS_TEST_LOG_NAME=maas17-after-final.txt \
bash scripts/test-controlled.sh
```

实际MySQL/Redis/SQL事务与Go relay参与，HTTP上游、批准profile和proof生产者仍为明确测试替身；没有Higress/模型/生产身份或A01–A34验收。原QA dbba820的19调用/9函数、d2的Usage20/Reader12及D1工具消费结论按原SHA保留，不以本轮开发者回归替代独立关项。本轮不改消费端或Chart来源锁，待新SHA由Mika交原QA后，再由运维沿原#5刷新。

公开Schema、票据v3、终态3.0、Observation1.0及所有旧迁移字节不变。c7顶层error锁存、首内容和有界D1导出修复保留；代码采样没有新增数据库写入。真实Callable保持关闭。

## 本轮作者结果

原TestMAAS17五个leaf：修复前2通过/3失败，修复后5/5通过，oracle字节未改。扩展R1事务提交前回滚1项、R1/R2边界4项、R3默认角色原子完成1项合计11/11 SQL/HTTP leaf通过；不与原QA或80/72等历史相加。

R3实际Activate将原Update operation完成；CloseAdmission在撤销UPDATE(state)时回滚且门禁保持开放；恢复该列后真实COMMIT丢ACK返回ErrCommitUnknown，用同CommandID恢复；Paused cleanup完成原Pause operation。action/spec_sha256/expected_rv写入返回1143，Key/预算/usage/DDL返回1142，拒绝结果原样记录。没有通过关闭hook、合并高权限角色或忽略SQL错误绕过。

中断前全仓Go事件103 pass/89 skip/0 fail（父/子事件；DB缺socket明确skip）、vet及命令构建通过；恢复后的追加金额actual/null及原slot检查另行定向记录。最初扩展Activate夹具因GatewayRef缺revision被原校验拒绝，已补合法测试引用；未改变原反例或产品校验。所有测试均为作者验证，R1–R3独立关项仍由原QA按新SHA给结论。

追加deadline测试最初350ms可能在准入阶段先到，日志maas17-money-slot.txt保留该未到目标边界的失败；最终改为finish Writer等待原5秒真实context截止，仍要求失败/未知actual/原held和slot不释放。不是放宽产品失败oracle，原TestMAAS17取消反例保持原字节。最终追加结果记录在maas17-money-slot-final.txt，和原11项分别记录、不累加为新验收总数。
