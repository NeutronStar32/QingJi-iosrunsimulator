// Browser checks exercise the page without sending any location command.
import { spawn } from 'node:child_process';
import { readFile, mkdir, writeFile, rm } from 'node:fs/promises';
import { setTimeout as pause } from 'node:timers/promises';
import assert from 'node:assert/strict';
import path from 'node:path';
import { existsSync } from 'node:fs';

const output = path.resolve('.local/testing');
await mkdir(output, { recursive: true });
const profile = path.join(output, 'browser-' + process.pid);
await mkdir(profile, { recursive: true });
const browserPath =
  process.env.QINGJI_BROWSER ||
  [process.env['ProgramFiles(x86)'], process.env.ProgramFiles]
    .filter(Boolean)
    .map((dir) => path.join(dir, 'Microsoft/Edge/Application/msedge.exe'))
    .find(existsSync);
assert(
  browserPath,
  'Microsoft Edge not found; set QINGJI_BROWSER to its executable path',
);
assert(
  profile.startsWith(output + path.sep),
  'Browser profile must stay in test output directory',
);
const browser = spawn(
  browserPath,
  [
    '--headless',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--remote-debugging-port=0',
    '--user-data-dir=' + profile,
    'about:blank',
  ],
  { windowsHide: true, stdio: 'ignore' },
);
let ws;
const pending = new Map();
let nextId = 1,
  session;
const devicePosts = [];
try {
  let port;
  for (let i = 0; i < 100; i++) {
    try {
      port = Number(
        (
          await readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')
        ).split('\n')[0],
      );
      break;
    } catch {
      await pause(100);
    }
  }
  assert(port, 'Browser did not start');
  const info = await (
    await fetch(`http://127.0.0.1:${port}/json/version`)
  ).json();
  ws = new WebSocket(info.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });
  function send(method, params = {}, sid) {
    const id = nextId++;
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        pending.delete(id);
        reject(Error('CDP timeout: ' + method));
      }, 15000);
      pending.set(id, { resolve, reject, timeout });
      ws.send(
        JSON.stringify({
          id,
          method,
          params,
          ...(sid ? { sessionId: sid } : {}),
        }),
      );
    });
  }
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.id) {
      const job = pending.get(data.id);
      if (job) {
        clearTimeout(job.timeout);
        pending.delete(data.id);
        data.error
          ? job.reject(Error(data.error.message))
          : job.resolve(data.result);
      }
    }
    if (data.method === 'Network.requestWillBeSent') {
      const request = data.params.request;
      if (
        request.method === 'POST' &&
        /\/api\/(set|clear|prepare|shutdown)(?:$|\?)/.test(request.url)
      )
        devicePosts.push(request.url);
    }
    // Prevent browsing test views from requesting additional public map tiles.
    if (data.method === 'Fetch.requestPaused') {
      send(
        'Fetch.fulfillRequest',
        {
          requestId: data.params.requestId,
          responseCode: 200,
          responseHeaders: [{ name: 'Content-Type', value: 'image/png' }],
          body: 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=',
        },
        session,
      ).catch(() => {});
    }
  };
  const target = await send('Target.createTarget', { url: 'about:blank' });
  session = (
    await send('Target.attachToTarget', {
      targetId: target.targetId,
      flatten: true,
    })
  ).sessionId;
  await send('Runtime.enable', {}, session);
  await send('Network.enable', {}, session);
  await send(
    'Emulation.setDeviceMetricsOverride',
    { width: 1440, height: 1500, deviceScaleFactor: 1, mobile: false },
    session,
  );
  const evaluate = async (expression) => {
    const r = await send(
      'Runtime.evaluate',
      { expression, returnByValue: true, awaitPromise: true },
      session,
    );
    if (r.exceptionDetails) throw Error(JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  await send(
    'Page.navigate',
    { url: process.env.QINGJI_TEST_URL || 'http://127.0.0.1:8765' },
    session,
  );
  for (let i = 0; i < 100; i++) {
    if (
      await evaluate(
        `Boolean(document.querySelector('#map.leaflet-container') && window.syncSentPoint)`,
      )
    )
      break;
    await pause(100);
  }
  assert(
    await evaluate(`Boolean(document.querySelector('#map.leaflet-container'))`),
    'Map initialized',
  );
  assert.equal(
    await evaluate(`window.calibrationRequested()`),
    true,
    'Verified local calibration is enabled by default',
  );
  await evaluate(`document.getElementById('calibrationEnabled').click()`);
  assert.equal(await evaluate(`window.calibrationRequested()`), false);
  assert.equal(
    await evaluate(`localStorage.getItem('qingji-calibration-enabled')`),
    'false',
    'Calibration choice persists',
  );
  await evaluate(`document.getElementById('calibrationEnabled').click()`);
  for (let i = 0; i < 150; i++) {
    if (
      await evaluate(
        `document.querySelectorAll('.leaflet-tile-loaded').length > 0 && document.querySelectorAll('.leaflet-tile:not(.leaflet-tile-loaded)').length === 0`,
      )
    )
      break;
    await pause(100);
  }
  const tileCount = await evaluate(
    `document.querySelectorAll('.leaflet-tile-loaded').length`,
  );
  console.log('Real viewport map tiles loaded:', tileCount);
  await pause(500);
  const screenshot = await send(
    'Page.captureScreenshot',
    { format: 'png', captureBeyondViewport: true },
    session,
  );
  await writeFile(
    path.join(output, 'map-preview.png'),
    Buffer.from(screenshot.data, 'base64'),
  );
  // All further map views use a test fixture, without accessing tile servers.
  await send(
    'Fetch.enable',
    { patterns: [{ urlPattern: 'https://tile.openstreetmap.org/*' }] },
    session,
  );
  assert.equal(await evaluate(`document.getElementById('latitude').value`), '');
  assert.equal(
    await evaluate(`document.querySelectorAll('.map-marker').length`),
    0,
  );
  const expectedCenter = await evaluate(
    `[qingjiMap.getCenter().lat,qingjiMap.getCenter().lng]`,
  );
  const rect = await evaluate(
    `(() => { const r = document.getElementById('map').getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()`,
  );
  await send(
    'Input.dispatchMouseEvent',
    { type: 'mousePressed', ...rect, button: 'left', clickCount: 1 },
    session,
  );
  await send(
    'Input.dispatchMouseEvent',
    { type: 'mouseReleased', ...rect, button: 'left', clickCount: 1 },
    session,
  );
  const point = await evaluate(
    `[Number(document.getElementById('latitude').value),Number(document.getElementById('longitude').value)]`,
  );
  assert(
    Math.abs(point[0] - expectedCenter[0]) < 1 &&
      Math.abs(point[1] - expectedCenter[1]) < 1,
    'Click fills geographic coordinates',
  );
  assert.equal(
    await evaluate(`document.querySelectorAll('.map-marker').length`),
    1,
  );
  const marker = await evaluate(
    `(() => { const r=document.querySelector('.map-marker').getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()`,
  );
  await send(
    'Input.dispatchMouseEvent',
    { type: 'mouseMoved', ...marker },
    session,
  );
  await send(
    'Input.dispatchMouseEvent',
    { type: 'mousePressed', ...marker, button: 'left', clickCount: 1 },
    session,
  );
  for (let n = 1; n <= 5; n++)
    await send(
      'Input.dispatchMouseEvent',
      {
        type: 'mouseMoved',
        x: marker.x + 10 * n,
        y: marker.y + 2 * n,
        button: 'left',
        buttons: 1,
      },
      session,
    );
  await send(
    'Input.dispatchMouseEvent',
    {
      type: 'mouseReleased',
      x: marker.x + 50,
      y: marker.y + 10,
      button: 'left',
      clickCount: 1,
    },
    session,
  );
  await pause(200);
  const dragged = await evaluate(`document.getElementById('longitude').value`);
  assert.notEqual(Number(dragged), point[1], 'Dragging updates coordinates');
  await evaluate(
    `document.getElementById('city').value='31.2304,121.4737';document.getElementById('city').dispatchEvent(new Event('change'));`,
  );
  assert.equal(
    await evaluate(`document.getElementById('longitude').value`),
    dragged,
    'City browsing preserves draft',
  );
  await evaluate(
    `document.getElementById('latitude').value='31.23';document.getElementById('longitude').value='121.47';document.getElementById('longitude').dispatchEvent(new Event('input'));document.getElementById('showCoordinates').click();`,
  );
  assert.equal(
    await evaluate(`document.querySelectorAll('.map-marker').length`),
    1,
  );
  assert.match(
    await evaluate(`document.getElementById('selectionHint').textContent`),
    /31.230000, 121.470000/,
  );
  await evaluate(`document.getElementById('resetSelection').click()`);
  assert.equal(await evaluate(`document.getElementById('latitude').value`), '');
  assert.equal(
    await evaluate(`document.querySelectorAll('.map-marker').length`),
    0,
  );
  // Synthetic report is confined to this test tab, never written to the real receiver.
  await evaluate(
    `window.renderPhone({active:false,addresses:[],report:{latitude:31.23,longitude:121.47,received_at:Date.now()/1000,mode_at_receive:'simulating'}})`,
  );
  assert.equal(
    await evaluate(
      `document.querySelectorAll('.phone-reported-marker').length`,
    ),
    1,
    'Phone report has a distinct marker',
  );
  assert.match(
    await evaluate(`document.getElementById('phoneReport').textContent`),
    /可能为模拟位置/,
  );
  assert.equal(
    await evaluate(`document.getElementById('latitude').value`),
    '',
    'Phone report does not populate a spoof target',
  );
  await evaluate(`document.getElementById('phoneCenter').click()`);
  assert.match(
    await evaluate(`document.getElementById('mapCaption').textContent`),
    /手机上报位置/,
  );
  await evaluate(
    `window.markLocationRestored();window.renderPhone({active:false,addresses:[],report:{latitude:31.23,longitude:121.47,received_at:Date.now()/1000-10,mode_at_receive:'simulating'}},{mode:'cleared'})`,
  );
  assert.equal(
    await evaluate(
      `document.querySelectorAll('.phone-reported-marker').length`,
    ),
    0,
    'Restore removes stale phone marker',
  );
  assert.equal(
    await evaluate(`document.querySelectorAll('.map-marker').length`),
    0,
    'Restore clears spoof draft',
  );
  assert.match(
    await evaluate(`document.getElementById('phoneReport').textContent`),
    /等待手机重新上报/,
  );
  await evaluate(
    `window.renderPhone({active:false,addresses:[],report:{latitude:31.24,longitude:121.48,received_at:Date.now()/1000+1,mode_at_receive:'cleared'}},{mode:'cleared'})`,
  );
  assert.equal(
    await evaluate(
      `document.querySelectorAll('.phone-reported-marker').length`,
    ),
    1,
    'Fresh report after restore becomes visible',
  );
  await evaluate(
    `document.getElementById('routeMode').click();document.getElementById('routeNew').click();routeEditor.addPoint(31.24,121.48);routeEditor.addPoint(31.241,121.48);routeEditor.addPoint(31.241,121.481)`,
  );
  assert.equal(await evaluate(`routeEditor.getDraft().points.length`), 3);
  assert.equal(
    await evaluate(`document.querySelectorAll('.route-marker').length`),
    3,
  );
  assert.equal(
    await evaluate(`document.getElementById('latitude').value`),
    '',
    'Route editing leaves single-point target untouched',
  );
  const openDistance = await evaluate(
    `Number(document.getElementById('routeStats').textContent.match(/· ([0-9.]+) 米/)[1])`,
  );
  await evaluate(`document.getElementById('routeClose').click()`);
  assert.equal(await evaluate(`routeEditor.getDraft().closed`), true);
  await evaluate(
    `document.getElementById('trajectoryPreviewPanel').open=true;document.getElementById('previewLaps').value=4;document.getElementById('previewRefresh').click()`,
  );
  assert.equal(await evaluate(`trajectoryPreview.snapshot().laps.length`), 4);
  const previewStart = await evaluate(`trajectoryPreview.snapshot().start`);
  const previewSeed = await evaluate(`trajectoryPreview.snapshot().seed`);
  await evaluate(`document.getElementById('previewRefresh').click()`);
  assert.deepEqual(
    await evaluate(`trajectoryPreview.snapshot().start`),
    previewStart,
  );
  assert.notEqual(
    await evaluate(`trajectoryPreview.snapshot().seed`),
    previewSeed,
  );
  await evaluate(
    `window.__previewOldState=window.trajectoryPreviewState;window.trajectoryPreviewState={mode:'simulating',target:trajectoryPreview.snapshot().laps[0].points[50]};document.getElementById('previewRefresh').click()`,
  );
  assert.deepEqual(
    await evaluate(`trajectoryPreview.snapshot().start`),
    await evaluate(`trajectoryPreviewState.target`),
  );
  await evaluate(
    `window.trajectoryPreviewState=window.__previewOldState;document.getElementById('trajectoryPreviewPanel').scrollIntoView()`,
  );
  const variationScreenshot = await send(
    'Page.captureScreenshot',
    { format: 'png', captureBeyondViewport: false },
    session,
  );
  await writeFile(
    path.join(output, 'trajectory-preview.png'),
    Buffer.from(variationScreenshot.data, 'base64'),
  );
  const closedDistance = await evaluate(
    `Number(document.getElementById('routeStats').textContent.match(/· ([0-9.]+) 米/)[1])`,
  );
  assert(closedDistance > openDistance, 'Distance includes closing segment');
  await evaluate(
    `(()=>{let line;qingjiMap.eachLayer(layer=>{if(layer instanceof L.Polyline && layer.options.color==='#b4773e')line=layer;});line.fire('click',{latlng:L.latLng(31.2405,121.48)});})()`,
  );
  assert.equal(
    await evaluate(`routeEditor.getDraft().points.length`),
    4,
    'Clicking line inserts route point',
  );
  await evaluate(`document.getElementById('routeUndo').click()`);
  assert.equal(await evaluate(`routeEditor.getDraft().points.length`), 3);
  await evaluate(
    `document.getElementById('map').scrollIntoView({block:'center'})`,
  );
  const routeMarker = await evaluate(
    `(()=>{const r=document.querySelector('.route-marker').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`,
  );
  const beforeRouteDrag = await evaluate(`routeEditor.getDraft().points[0][1]`);
  await send(
    'Input.dispatchMouseEvent',
    { type: 'mouseMoved', ...routeMarker },
    session,
  );
  await send(
    'Input.dispatchMouseEvent',
    { type: 'mousePressed', ...routeMarker, button: 'left', clickCount: 1 },
    session,
  );
  for (let n = 1; n <= 4; n++)
    await send(
      'Input.dispatchMouseEvent',
      {
        type: 'mouseMoved',
        x: routeMarker.x + 8 * n,
        y: routeMarker.y + 2 * n,
        button: 'left',
        buttons: 1,
      },
      session,
    );
  await send(
    'Input.dispatchMouseEvent',
    {
      type: 'mouseReleased',
      x: routeMarker.x + 32,
      y: routeMarker.y + 8,
      button: 'left',
      clickCount: 1,
    },
    session,
  );
  assert.notEqual(
    await evaluate(`routeEditor.getDraft().points[0][1]`),
    beforeRouteDrag,
    'Route point is draggable',
  );
  await evaluate(
    `document.getElementById('routeUndo').click();document.querySelectorAll('#routePoints li button')[4].click()`,
  );
  await evaluate(`document.getElementById('routeDeletePoint').click()`);
  assert.equal(
    await evaluate(`routeEditor.getDraft().closed`),
    false,
    'Deleting third point opens route',
  );
  await evaluate(`document.getElementById('routeUndo').click()`);
  assert.equal(
    await evaluate(`routeEditor.getDraft().closed`),
    true,
    'Undo restores closed route',
  );
  await evaluate(`document.getElementById('routeRedo').click()`);
  assert.equal(await evaluate(`routeEditor.getDraft().points.length`), 2);
  await evaluate(
    `document.getElementById('routeUndo').click();document.getElementById('routeName').value='界面检查_'+Date.now();document.getElementById('routeSave').click()`,
  );
  for (let i = 0; i < 100; i++) {
    if (
      await evaluate(
        `document.getElementById('routeFeedback').textContent.startsWith('已保存')`,
      )
    )
      break;
    await pause(100);
  }
  const savedId = await evaluate(`routeEditor.getDraft().id`);
  assert.match(
    savedId,
    /^[a-f0-9]{32}$/,
    'Route is saved on local backend: ' +
      (await evaluate(`document.getElementById('routeFeedback').textContent`)),
  );
  await evaluate(
    `document.getElementById('routeNew').click();document.getElementById('savedRoutes').value=${JSON.stringify(savedId)};document.getElementById('routeLoad').click()`,
  );
  assert.equal(await evaluate(`routeEditor.getDraft().points.length`), 3);
  assert.equal(await evaluate(`routeEditor.getDraft().closed`), true);
  await pause(500); // Wait for Leaflet's fitBounds animation before visual inspection.
  assert(
    await evaluate(
      `routeEditor.getDraft().points.every(p=>qingjiMap.getBounds().contains(p))`,
    ),
    'Loaded route is inside map view',
  );
  assert.equal(
    await evaluate(
      `Array.from(document.querySelectorAll('.route-marker')).filter(e=>{const r=e.getBoundingClientRect(),m=document.getElementById('map').getBoundingClientRect();return r.x>=m.x&&r.right<=m.right&&r.y>=m.y&&r.bottom<=m.bottom;}).length`,
    ),
    3,
    'All route markers are visibly inside the map',
  );
  const routePreview = await send(
    'Page.captureScreenshot',
    { format: 'png', captureBeyondViewport: true },
    session,
  );
  await writeFile(
    path.join(output, 'route-preview.png'),
    Buffer.from(routePreview.data, 'base64'),
  );
  await evaluate(`document.getElementById('routeDelete').click()`);
  for (let i = 0; i < 100; i++) {
    if (
      await evaluate(
        `document.getElementById('routeFeedback').textContent.startsWith('已删除')`,
      )
    )
      break;
    await pause(100);
  }
  assert.equal(
    await evaluate(
      `Array.from(document.getElementById('savedRoutes').options).some(o=>o.value===${JSON.stringify(savedId)})`,
    ),
    false,
    'Test route cleaned up',
  );
  await evaluate(
    `document.getElementById('routeShape').value='smooth';document.getElementById('routeShape').dispatchEvent(new Event('change'))`,
  );
  assert.equal(
    await evaluate(`routeEditor.getDraft().editor.control_points.length`),
    3,
  );
  assert(
    await evaluate(`routeEditor.getDraft().points.length>3`),
    'Smoothed preview is exported as sampled curve',
  );
  await evaluate(`document.getElementById('routeTrackCreate').click()`);
  assert.equal(await evaluate(`routeEditor.getDraft().editor.mode`), 'track');
  await evaluate(
    `document.getElementById('previewLaps').value=3;document.getElementById('previewRefresh').click();document.getElementById('trajectoryPreviewPanel').scrollIntoView()`,
  );
  assert.equal(await evaluate(`trajectoryPreview.snapshot().laps.length`), 3);
  await pause(700);
  const trackVariationScreenshot = await send(
    'Page.captureScreenshot',
    { format: 'png', captureBeyondViewport: false },
    session,
  );
  await writeFile(
    path.join(output, 'trajectory-track-preview.png'),
    Buffer.from(trackVariationScreenshot.data, 'base64'),
  );
  assert.equal(
    await evaluate(`document.querySelectorAll('.track-handle').length`),
    3,
  );
  assert.equal(await evaluate(`routeEditor.getDraft().closed`), true);
  await evaluate(
    `document.getElementById('trackLength').value=180;document.getElementById('trackWidth').value=60;document.getElementById('trackAngle').value=35;document.getElementById('trackAngle').dispatchEvent(new Event('change'))`,
  );
  assert.equal(await evaluate(`routeEditor.getDraft().editor.track.angle`), 35);
  assert.equal(
    await evaluate(`trajectoryPreview.snapshot()`),
    null,
    'Changing route invalidates old preview',
  );
  const centerBefore = await evaluate(
    `routeEditor.getDraft().editor.track.center[0]`,
  );
  await evaluate(
    `void qingjiMap.eachLayer(group=>{if(group instanceof L.LayerGroup)group.eachLayer(m=>{if(m instanceof L.Marker&&m.options.title==='移动'){m.fire('dragstart');const p=m.getLatLng();m.setLatLng([p.lat+.0001,p.lng]);m.fire('dragend');}});})`,
  );
  assert(
    Math.abs(
      (await evaluate(`routeEditor.getDraft().editor.track.center[0]`)) -
        centerBefore -
        0.0001,
    ) < 1e-8,
    'Center handle moves entire track',
  );
  await evaluate(
    `document.getElementById('routeName').value='模板检查_'+Date.now();document.getElementById('routeSave').click()`,
  );
  await pause(300);
  const templateId = await evaluate(`routeEditor.getDraft().id`);
  assert.match(templateId, /^[a-f0-9]{32}$/);
  await evaluate(
    `document.getElementById('routeNew').click();document.getElementById('savedRoutes').value=${JSON.stringify(templateId)};document.getElementById('routeLoad').click()`,
  );
  assert.equal(
    await evaluate(`routeEditor.getDraft().editor.track.width`),
    60,
    'Saved template keeps editable dimensions',
  );
  assert.equal(
    await evaluate(`document.querySelectorAll('.track-handle').length`),
    3,
  );
  const templatePreview = await send(
    'Page.captureScreenshot',
    { format: 'png', captureBeyondViewport: true },
    session,
  );
  await writeFile(
    path.join(output, 'route-preview.png'),
    Buffer.from(templatePreview.data, 'base64'),
  );
  await evaluate(`document.getElementById('routeDelete').click()`);
  await pause(300);
  await send(
    'Emulation.setDeviceMetricsOverride',
    { width: 390, height: 844, deviceScaleFactor: 1, mobile: true },
    session,
  );
  await pause(300);
  assert(
    await evaluate(`document.documentElement.scrollWidth <= window.innerWidth`),
    'Mobile has no horizontal overflow',
  );
  assert.equal(
    devicePosts.length,
    0,
    'Map interactions never send phone commands',
  );
  // UI commands below are intercepted inside this disposable tab, never sent to the real phone.
  await evaluate(`(async()=>{
    const original=window.fetch.bind(window);window.__mockState=await(await original('/api/status')).json();window.__mockRequests=[];
    window.__mockState.mode='untouched';window.__mockState.target=null;window.__mockState.run={status:'idle',message:'尚未开始跑步。',distance_m:0,moving_seconds:0,position:null,completed_laps:0,current_lap:0,lap_length_m:0,laps:0,pace_seconds:null,connected:false,route:null};
    window.fetch=async(input,options={})=>{
      const pathname=new URL(input,location.href).pathname;
      if(pathname==='/api/status')return new Response(JSON.stringify(window.__mockState));
      if(pathname.startsWith('/api/run-')||pathname==='/api/shutdown'){
        const body=JSON.parse(options.body||'{}');window.__mockRequests.push({pathname,body});
        const state=window.__mockState;
        if(pathname==='/api/run-start'){state.mode='simulating';state.target=body.route.points[0];state.run={status:'running',message:'正在沿路线移动。',distance_m:0,moving_seconds:0,position:state.target,completed_laps:0,current_lap:1,lap_length_m:353,laps:body.laps,pace_seconds:body.pace_seconds,connected:true,route:body.route};}
        if(pathname==='/api/run-pause'){state.run.status='paused';state.run.message='已暂停，定位保持原地。';}
        if(pathname==='/api/run-resume'){state.run.status='running';state.run.message='已继续，从暂停的位置沿路线移动。';}
        if(pathname==='/api/run-stop')state.run.status='stopped';
        if(pathname==='/api/shutdown')await new Promise(resolve=>setTimeout(resolve,500));
        return new Response(JSON.stringify({ok:true,state}));
      }
      return original(input,options);
    };
    render(window.__mockState);
  })()`);
  async function waitFor(expression) {
    for (let i = 0; i < 60; i++) {
      if (await evaluate(expression)) return;
      await pause(50);
    }
    throw Error('UI condition timed out: ' + expression);
  }
  await evaluate(
    `document.getElementById('runGeneratedTrajectory').checked=false;refreshRunControls();document.getElementById('runStart').click()`,
  );
  await waitFor(`document.getElementById('runBadge').textContent==='跑步中'`);
  assert.equal(
    await evaluate(`window.__mockRequests[0].body.pace_seconds`),
    360,
    'Pace sent as seconds per kilometer',
  );
  assert.equal(
    await evaluate(`window.__mockRequests[0].body.calibration_enabled`),
    true,
    'Run sends the selected calibration switch',
  );
  assert.equal(
    await evaluate(`window.__mockRequests[0].body.pace_variation_seconds`),
    15,
  );
  assert.equal(
    await evaluate(`window.__mockRequests[0].body.trajectory_offset_m`),
    0.8,
  );
  assert.equal(
    await evaluate(`document.getElementById('paceVariation').disabled`),
    true,
  );
  await evaluate(
    `window.__mockState.run.calibration={active:true,message:'本次定位已应用操场偏移修正。'};render(window.__mockState)`,
  );
  assert.match(
    await evaluate(`document.getElementById('calibrationStatus').textContent`),
    /已应用操场偏移修正/,
  );
  await evaluate(`document.getElementById('runPause').click()`);
  await waitFor(`document.getElementById('runBadge').textContent==='休息中'`);
  assert.equal(
    await evaluate(`document.getElementById('runPause').textContent`),
    '继续跑步',
  );
  await evaluate(`document.getElementById('runPause').click()`);
  await waitFor(`document.getElementById('runBadge').textContent==='跑步中'`);
  await evaluate(
    `window.__mockState.run.distance_m=125;window.__mockState.run.moving_seconds=45;render(window.__mockState)`,
  );
  assert.match(
    await evaluate(`document.getElementById('runDistance').textContent`),
    /125.0/,
  );
  assert.equal(
    await evaluate(`document.getElementById('runTime').textContent`),
    '00:45',
  );
  await evaluate(
    `document.querySelector('.run-card').scrollIntoView({block:'center'})`,
  );
  const runningPreview = await send(
    'Page.captureScreenshot',
    { format: 'png', captureBeyondViewport: false },
    session,
  );
  await writeFile(
    path.join(output, 'running-preview.png'),
    Buffer.from(runningPreview.data, 'base64'),
  );
  await evaluate(`document.getElementById('runStop').click()`);
  await waitFor(`document.getElementById('runBadge').textContent==='已结束'`);
  await evaluate(
    `document.getElementById('paceVariationEnabled').checked=false;document.getElementById('trajectoryOffsetEnabled').checked=false;document.getElementById('runStart').click()`,
  );
  await waitFor(`document.getElementById('runBadge').textContent==='跑步中'`);
  assert.equal(
    await evaluate(
      `window.__mockRequests.filter(r=>r.pathname==='/api/run-start').at(-1).body.pace_variation_seconds`,
    ),
    0,
    'Pace variation can be disabled',
  );
  assert.equal(
    await evaluate(
      `window.__mockRequests.filter(r=>r.pathname==='/api/run-start').at(-1).body.trajectory_offset_m`,
    ),
    0,
    'Trajectory variation can be disabled',
  );
  await evaluate(`document.getElementById('runStop').click()`);
  await waitFor(`document.getElementById('runBadge').textContent==='已结束'`);
  await evaluate(
    `document.getElementById('runGeneratedTrajectory').checked=true;refreshRunControls();document.getElementById('previewRefresh').click()`,
  );
  const selectedSeed = await evaluate(`trajectoryPreview.snapshot().seed`);
  const selectedAnchor = await evaluate(`trajectoryPreview.snapshot().start`);
  await evaluate(
    `document.getElementById('runInfinite').checked=true;document.getElementById('runStart').click()`,
  );
  await waitFor(`document.getElementById('runBadge').textContent==='跑步中'`);
  const generatedRequest = await evaluate(
    `window.__mockRequests.filter(r=>r.pathname==='/api/run-start').at(-1).body`,
  );
  assert.equal(
    generatedRequest.trajectory.seed,
    selectedSeed,
    'Actual run reuses preview seed',
  );
  assert.deepEqual(
    generatedRequest.trajectory.anchor,
    selectedAnchor,
    'Actual run reuses preview anchor',
  );
  assert.equal(
    generatedRequest.laps,
    0,
    'Generated mode supports infinite runs',
  );
  assert.equal(
    generatedRequest.trajectory_offset_m,
    0,
    'No double application of old jitter',
  );
  assert.equal(
    await evaluate(
      `document.getElementById('runGeneratedTrajectory').disabled`,
    ),
    true,
  );
  await evaluate(`document.getElementById('previewRefresh').click()`);
  assert.equal(
    await evaluate(
      `window.__mockRequests.filter(r=>r.pathname==='/api/run-start').at(-1).body.trajectory.seed`,
    ),
    selectedSeed,
    'Refreshing preview leaves active task unchanged',
  );
  await evaluate(`document.getElementById('runStop').click()`);
  await waitFor(`document.getElementById('runBadge').textContent==='已结束'`);
  await evaluate(
    `window.scrollTo(0,document.body.scrollHeight);document.getElementById('exitApp').click()`,
  );
  assert.match(
    await evaluate(`document.getElementById('exitStatus').textContent`),
    /正在退出/,
  );
  await waitFor(
    `document.getElementById('exitStatus').textContent.includes('已退出')`,
  );
  assert(
    await evaluate(
      `(()=>{const r=document.getElementById('exitStatus').getBoundingClientRect();return r.top>=0&&r.bottom<=window.innerHeight;})()`,
    ),
    'Exit result stays visible beside button even when scrolled down',
  );
  const exitPreview = await send(
    'Page.captureScreenshot',
    { format: 'png', captureBeyondViewport: false },
    session,
  );
  await writeFile(
    path.join(output, 'exit-preview.png'),
    Buffer.from(exitPreview.data, 'base64'),
  );
  assert.equal(
    devicePosts.length,
    0,
    'Run and shutdown UI tests never send real phone commands',
  );
  console.log(
    'PASS: map/routes, running controls and metrics, exit status next to button, mobile layout; no real phone writes.',
  );
} finally {
  if (ws?.readyState === 1) {
    ws.send(JSON.stringify({ id: nextId++, method: 'Browser.close' }));
    await pause(300);
    ws.close();
  }
  for (const job of pending.values()) clearTimeout(job.timeout);
  if (browser.exitCode === null) browser.kill();
  await pause(300);
  await rm(profile, {
    recursive: true,
    force: true,
    maxRetries: 5,
    retryDelay: 100,
  }).catch(() => {});
}
