const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function load() {
  const nodes = new Map();
  const document = {
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, { textContent: '', appendChild() {}, scrollHeight: 0 });
      return nodes.get(id);
    },
    createElement() { return { textContent: '', className: '' }; },
  };
  class AudioContext {
    currentTime = 0;
    state = 'running';
    destination = {};
    createBuffer(channels, size) { return { getChannelData: () => new Float32Array(size) }; }
    createBufferSource() {
      return { connect() {}, start() {}, stop() { this.onended?.(); } };
    }
  }
  const context = vm.createContext({ document, AudioContext, console, setTimeout, clearTimeout, Float32Array, Int16Array, Uint8Array, atob });
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'static/app.js'), 'utf8'), context);
  return { Player: vm.runInContext('PcmPlayer', context), context };
}

test('story mode follows current turn and clears when connection stops', () => {
  const { context } = load();
  vm.runInContext('handleJson({type:"turn_start",turn_id:1}); handleJson({type:"story_mode",turn_id:1,phase:"playing"});', context);
  assert.match(context.document.getElementById('storyMode').textContent, /故事进行中/);
  vm.runInContext('handleJson({type:"turn_start",turn_id:2}); handleJson({type:"story_mode",turn_id:1,phase:"off"});', context);
  assert.match(context.document.getElementById('storyMode').textContent, /故事进行中/);
  vm.runInContext('stop()', context);
  assert.equal(context.document.getElementById('storyMode').textContent, '');
});

test('temporary queue gap does not acknowledge an unfinished audio stream', () => {
  const { Player } = load();
  const ended = [];
  const player = new Player(id => ended.push(id));
  assert.equal(typeof player.begin, 'function', 'Player needs explicit turn boundaries');
  player.begin(1);
  player.push(new Int16Array(20), 1);
  player.sources[0].onended();
  assert.equal(ended.length, 0);
  player.push(new Int16Array(20), 1);
  player.finish(1);
  assert.equal(ended.length, 0);
  player.sources[0].onended();
  assert.deepEqual(ended, [1]);
  player.finish(1);
  assert.deepEqual(ended, [1]);
});

test('late ended callbacks and chunks from an interrupted turn cannot finish the new turn', () => {
  const { Player } = load();
  const ended = [];
  const player = new Player(id => ended.push(id));
  assert.equal(typeof player.begin, 'function');
  player.begin(1);
  player.push(new Int16Array(20), 1);
  const oldSource = player.sources[0];
  player.begin(2);
  player.push(new Int16Array(20), 1);
  assert.equal(player.sources.length, 0);
  oldSource.onended();
  player.finish(1);
  assert.equal(ended.length, 0);
  player.finish(2);
  assert.deepEqual(ended, [2]);
});

test('stopped playback never emits a completion acknowledgement', () => {
  const { Player } = load();
  const ended = [];
  const player = new Player(id => ended.push(id));
  assert.equal(typeof player.begin, 'function');
  player.begin(1);
  player.push(new Int16Array(20), 1);
  player.finish(1);
  player.stop();
  assert.equal(ended.length, 0);
});
