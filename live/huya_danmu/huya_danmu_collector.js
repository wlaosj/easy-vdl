#!/usr/bin/env node
/**
 * Huya Danmu Collector - 独立弹幕采集进程
 * Usage: node huya_danmu_collector.js <room_id> <output_path>
 *
 * 写入弹幕到 output_path.danmu.jsonl
 */
import huya_danmu from "./index.js";
import fs from "fs";

const [,, roomId, outputPath = "", anchorName = "", saveFileArg = "true"] = process.argv;
const saveFile = saveFileArg !== "false";

if (!roomId || (saveFile && !outputPath)) {
  console.error(`Usage: node huya_danmu_collector.js <room_id> <output_path> [anchor_name] [save_file]
  roomId: Huya room ID (numeric or short ID)
  outputPath: Path to output video file (弹幕会写入 .danmu.jsonl)`);
  process.exit(1);
}

const danmuPath = saveFile ? outputPath.replace(/\.[^.]+$/, "") + ".danmu.jsonl" : "";
const danmuIdxPath = saveFile ? outputPath.replace(/\.[^.]+$/, "") + ".danmu.idx.jsonl" : "";
const dir = saveFile ? danmuPath.substring(0, danmuPath.lastIndexOf("/")) : "";

if (saveFile && !fs.existsSync(dir)) {
  fs.mkdirSync(dir, { recursive: true });
}

const fileHandle = saveFile ? fs.createWriteStream(danmuPath, { flags: "a", encoding: "utf8" }) : null;
const idxHandle = saveFile ? fs.createWriteStream(danmuIdxPath, { flags: "a", encoding: "utf8" }) : null;

// 索引：每分钟记录一次字节偏移
let lastMinuteTs = Math.floor(Date.now() / 60000) * 60;
const writeIdx = () => {
  if (!saveFile || !idxHandle || !danmuPath) return;
  const stat = fs.statSync(danmuPath);
  const currentMinuteTs = Math.floor(Date.now() / 60000) * 60;
  if (currentMinuteTs > lastMinuteTs) {
    idxHandle.write(JSON.stringify({ minute_ts: currentMinuteTs, offset: stat.size }) + "\n");
    lastMinuteTs = currentMinuteTs;
  }
};

console.log(JSON.stringify({ type: "log", ts: Date.now() / 1000, msg: `Starting huya danmu collector: room=${roomId}, output=${danmuPath}` }));

const client = new huya_danmu(roomId);

client.on("connect", () => {
  console.log(JSON.stringify({ type: "log", ts: Date.now() / 1000, msg: `Connected to huya room ${roomId}` }));
});

client.on("message", (msg) => {
  if (msg.type === "chat") {
    const event = {
      type: "danmu",
      ts: msg.time / 1000,  // 毫秒转秒级浮点数
      event_type: "chat",
      content: msg.content || "",
      user: { id: msg.from?.rid || "", name: msg.from?.name || "" },
      color: msg.color || "#ffffff",
    };
    if (fileHandle) fileHandle.write(JSON.stringify(event) + "\n");
    writeIdx();
    // 输出弹幕事件到 stdout，用于实时推送
    console.log(JSON.stringify({ type: "danmu_event", ts: Date.now() / 1000, event }));
  } else if (msg.type === "gift") {
    const event = {
      type: "danmu",
      ts: msg.time / 1000,
      event_type: "gift",
      content: "",
      user: { id: msg.from?.rid || "", name: msg.from?.name || "" },
      gift: { name: msg.name || "", count: msg.count || 1 },
    };
    if (fileHandle) fileHandle.write(JSON.stringify(event) + "\n");
    writeIdx();
    console.log(JSON.stringify({ type: "danmu_event", ts: Date.now() / 1000, event }));
  } else if (msg.type === "online") {
    console.log(JSON.stringify({ type: "status", ts: Date.now() / 1000, online: msg.count }));
  }
});

client.on("error", (err) => {
  console.log(JSON.stringify({ type: "error", ts: Date.now() / 1000, msg: String(err) }));
});

// Start receiving danmu
client.start();

// Handle stop command
process.stdin.setEncoding("utf8");
process.stdin.on("data", (data) => {
  try {
    const cmd = JSON.parse(data.trim());
    if (cmd.cmd === "stop") {
      console.log(JSON.stringify({ type: "log", ts: Date.now() / 1000, msg: "Stopping..." }));
      client.stop();
      if (fileHandle) fileHandle.end();
      if (idxHandle) idxHandle.end();
      process.exit(0);
    }
  } catch (e) {
    // Ignore
  }
});

// Handle process termination
process.on("SIGINT", () => {
  client.stop();
  if (fileHandle) fileHandle.end();
  if (idxHandle) idxHandle.end();
  process.exit(0);
});

process.on("SIGTERM", () => {
  client.stop();
  if (fileHandle) fileHandle.end();
  if (idxHandle) idxHandle.end();
  process.exit(0);
});

console.log(JSON.stringify({ type: "log", ts: Date.now() / 1000, msg: `Danmu collector started for room ${roomId}` }));
