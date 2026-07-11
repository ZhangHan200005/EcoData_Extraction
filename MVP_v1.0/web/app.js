const state = {data: null, selected: null, selectedFigure: null};
const $ = selector => document.querySelector(selector);
const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));

function toast(message) { const el = $("#toast"); el.textContent = message; el.style.display = "block"; setTimeout(() => el.style.display = "none", 3500); }
async function request(url, options) { const response = await fetch(url, options); const body = await response.json(); if (!response.ok) throw new Error(body.error || response.statusText); return body; }

async function loadState() {
  state.data = await request("/api/state");
  const run = state.data.run;
  $("#run-meta").textContent = run ? `${run.run_id} · ${run.unique_study_count} 篇论文` : "尚未运行，请上传 PDF 后运行抽取";
  $("#report-link").href = run ? `${state.data.run_url}quality_report.html` : "#";
  const summary = state.data.summary || {};
  $("#summary").innerHTML = `<span><strong>${summary.study_count || 0}</strong> 篇论文</span><span><strong>${summary.candidate_count || 0}</strong> 条候选</span><span><strong>${Math.round((summary.traceable_candidate_rate || 0) * 100)}%</strong> 可追溯</span><span><strong>${summary.issue_count || 0}</strong> 个 QC 提示</span>`;
  const variables = [...new Set(state.data.candidates.map(row => row.variable_name))].sort();
  $("#variable-filter").innerHTML = '<option value="">全部变量</option>' + variables.map(value => `<option>${escapeHtml(value)}</option>`).join("");
  renderCandidates(); renderStudies(); renderIssues(); renderFigures();
}

function renderCandidates() {
  const variable = $("#variable-filter").value; const status = $("#status-filter").value; const query = $("#search").value.toLowerCase();
  const rows = (state.data?.candidates || []).filter(row => (!variable || row.variable_name === variable) && (!status || row.review_status === status) && (!query || `${row.evidence_text} ${row.study_id}`.toLowerCase().includes(query)));
  $("#candidate-list").innerHTML = rows.map(row => `<button class="list-item ${state.selected?.candidate_id === row.candidate_id ? "active" : ""}" data-id="${row.candidate_id}"><strong>${escapeHtml(row.variable_name)}</strong><span class="badge">${escapeHtml(row.review_status)}</span><span>${escapeHtml(row.value_normalized || row.value_text || row.value_raw)} ${escapeHtml(row.unit_normalized)}</span><small>p.${row.page} · ${escapeHtml(row.source_type)} · confidence ${row.confidence}</small></button>`).join("") || '<div class="empty">没有符合筛选条件的候选</div>';
  document.querySelectorAll("#candidate-list .list-item").forEach(button => button.addEventListener("click", () => selectCandidate(button.dataset.id)));
}

function selectCandidate(id) {
  state.selected = state.data.candidates.find(row => row.candidate_id === id); renderCandidates();
  const row = state.selected; const study = state.data.studies.find(item => item.study_id === row.study_id) || {};
  $("#candidate-detail").classList.remove("empty");
  $("#candidate-detail").innerHTML = `<h2>${escapeHtml(row.variable_name)}</h2><p><strong>${escapeHtml(row.value_normalized || row.value_text || row.value_raw)} ${escapeHtml(row.unit_normalized)}</strong> · ${escapeHtml(study.title || row.study_id)}</p><p><a href="/pdfs/${encodeURIComponent(study.pdf_filename)}#page=${row.page}" target="_blank">打开 PDF 第 ${row.page} 页</a> · ${escapeHtml(row.source_locator)}</p><h3>原始证据</h3><div class="evidence">${escapeHtml(row.evidence_text)}</div><div class="field"><label>修改后的值</label><input id="new-value" value="${escapeHtml(row.value_normalized || row.value_text || "")}"></div><div class="field"><label>修改/拒绝/不确定的原因</label><textarea id="review-reason"></textarea></div><div class="field"><label>审核人</label><input id="reviewer" value="local-reviewer"></div><div class="review-actions"><button data-action="accepted">接受</button><button data-action="modified">修改并接受</button><button data-action="uncertain">无法确定</button><button data-action="rejected">拒绝</button></div>`;
  document.querySelectorAll(".review-actions button").forEach(button => button.addEventListener("click", () => submitReview(button.dataset.action)));
}

async function submitReview(action) {
  try {
    await request("/api/review", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({candidate_id:state.selected.candidate_id, action, new_value:$("#new-value").value, reason:$("#review-reason").value, reviewer:$("#reviewer").value})});
    toast("审核记录已保存"); await loadState();
  } catch (error) { toast(error.message); }
}

function renderTable(selector, rows, columns) {
  const target = $(selector); if (!rows.length) { target.innerHTML = '<div class="empty">暂无数据</div>'; return; }
  target.innerHTML = `<table><thead><tr>${columns.map(col => `<th>${escapeHtml(col)}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${columns.map(col => `<td class="${escapeHtml(row.severity || "")}">${escapeHtml(row[col])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
function renderStudies() { renderTable("#studies-table", state.data?.studies || [], ["study_id","title","publication_year","language","screening_status","target_hit_count","doi","pdf_filename"]); }
function renderIssues() { renderTable("#issues-table", state.data?.issues || [], ["severity","issue_type","study_id","page","message","status"]); }

function renderFigures() {
  const rows = state.data?.figures || [];
  $("#figure-list").innerHTML = rows.map(row => `<button class="list-item" data-id="${row.task_id}"><strong>${escapeHtml(row.figure_label)}</strong><span class="badge">${escapeHtml(row.status)}</span><span>第 ${row.page} 页</span><small>${escapeHtml(row.caption).slice(0,100)}</small></button>`).join("") || '<div class="empty">未发现图件任务</div>';
  document.querySelectorAll("#figure-list .list-item").forEach(button => button.addEventListener("click", () => selectFigure(button.dataset.id)));
}

async function selectFigure(id) {
  const row = state.data.figures.find(item => item.task_id === id); state.selectedFigure = row;
  const study = state.data.studies.find(item => item.study_id === row.study_id) || {};
  const imageUrl = row.image_path ? `${state.data.run_url}${row.image_path}` : "";
  $("#figure-detail").innerHTML = `<strong>${escapeHtml(study.title || row.study_id)} · ${escapeHtml(row.figure_label)}</strong><p>${escapeHtml(row.caption)}</p>${imageUrl ? `<img class="figure-preview" src="${imageUrl}" alt="${escapeHtml(row.figure_label)}"><div class="axis-grid"><input id="x-label" placeholder="X轴名称"><input id="x-unit" placeholder="X单位"><input id="y-label" placeholder="Y轴名称"><input id="y-unit" placeholder="Y单位"></div><button id="load-wpd" class="primary">载入 WPD</button> <button id="save-wpd">保存当前数据</button> <button id="bundle-wpd">打包已保存 CSV</button>` : '<p class="warning">自动裁剪失败，需要人工指定图件区域。</p>'}`;
  if (imageUrl) $("#load-wpd").addEventListener("click", () => loadIntoWpd(imageUrl, `${row.task_id}.png`));
  if (imageUrl) $("#save-wpd").addEventListener("click", saveWpdOutput);
  if (imageUrl) $("#bundle-wpd").addEventListener("click", bundleWpdOutput);
}

async function loadIntoWpd(url, filename) {
  try {
    const frame = $("#wpd-frame"); const blob = await (await fetch(url)).blob(); const file = new File([blob], filename, {type:"image/png"});
    for (let i=0;i<100;i+=1) { const app = frame.contentWindow?.wpd; if (app?.imageManager) { app.appData.reset(); app.appData.setPageManager(null); app.sidebar.clear(); app.imageManager.initializeFileManager([file], true); await app.imageManager.loadFromFile(file); app.popup.close("loadNewImage"); app.calibrateAxesDialog.open(); toast("已载入本地图件，请标定坐标系"); return; } await new Promise(resolve => setTimeout(resolve,250)); }
    throw new Error("WPD 尚未就绪");
  } catch (error) { toast(error.message); }
}

async function saveWpdOutput() {
  try {
    const app = $("#wpd-frame").contentWindow.wpd; const plotData = app.appData.getPlotData(); const datasets = [];
    plotData.getDatasets().forEach(dataset => { const axes=plotData.getAxesForDataset(dataset); if(!axes)return; app.plotDataProvider.setDataSource(dataset); const data=app.plotDataProvider.getData(); datasets.push({name:dataset.name || "dataset", fields:[...data.fields], rows:data.rawData.map(row => [...row])}); });
    const points=datasets.reduce((total,dataset)=>total+dataset.rows.length,0); if(!points) throw new Error("WPD 当前没有可保存的数据点");
    const result=await request("/api/figure-save",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({task_id:state.selectedFigure.task_id,x_label:$("#x-label").value,x_unit:$("#x-unit").value,y_label:$("#y-label").value,y_unit:$("#y-unit").value,datasets})});
    toast(`已保存 ${result.figure_review.point_count} 个点`); await loadState();
  } catch(error) { toast(error.message); }
}

async function bundleWpdOutput() {
  try { const result=await request("/api/figure-bundle",{method:"POST"}); const link=document.createElement("a"); link.href=result.url; link.click(); toast("图数据 CSV 已打包"); } catch(error) { toast(error.message); }
}

document.querySelectorAll(".tab").forEach(tab => tab.addEventListener("click", () => { document.querySelectorAll(".tab,.view").forEach(el => el.classList.remove("active")); tab.classList.add("active"); $(`#${tab.dataset.view}-view`).classList.add("active"); }));
[$("#variable-filter"),$("#status-filter")].forEach(el => el.addEventListener("change", renderCandidates)); $("#search").addEventListener("input", renderCandidates);
$("#pdf-input").addEventListener("change", async event => { for (const file of event.target.files) { try { await request("/api/upload", {method:"POST", headers:{"X-Filename":encodeURIComponent(file.name)}, body:file}); toast(`${file.name} 已上传`); } catch(error) { toast(error.message); } } });
$("#run-button").addEventListener("click", async () => { const button=$("#run-button"); button.disabled=true; button.textContent="运行中..."; try { const result=await request("/api/run",{method:"POST"}); toast(`${result.run_id} 已完成`); await loadState(); } catch(error){toast(error.message);} finally{button.disabled=false;button.textContent="运行抽取";} });
loadState().catch(error => toast(error.message));
