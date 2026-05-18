/**
 * 本来打算直接用 douyudm 这个库，但有比较多的地方不符合我的需求，
 * 所以参考着这个库以及斗鱼的代码进行了重新实现。
 * reference: https://github.com/flxxyz/douyudm
 */
import WebSocket from "ws";
import mitt from "mitt";
import { BufferCoder } from "./buffer_coder.js";
import { STT } from "./stt.js";
export function createDYClient(channelId, opts = {}) {
    let ws = null;
    let maxRetry = 10;
    let coder = new BufferCoder();
    let heartbeatTimer = null;
    const send = (message) => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws?.send(coder.encode(STT.serialize(message)));
        }
    };
    const sendLogin = () => send({ type: "loginreq", roomid: channelId });
    const sendJoinGroup = () => send({ type: "joingroup", rid: channelId, gid: -9999 });
    const sendHeartbeat = () => {
        if (ws?.readyState !== WebSocket.OPEN) {
            return;
        }
        send({ type: "mrkl" });
    };
    const sendLogout = () => send({ type: "logout" });
    const onOpen = () => {
        sendLogin();
        sendJoinGroup();
        heartbeatTimer = setInterval(sendHeartbeat, 45e3);
    };
    const onClose = () => {
        sendLogout();
        if (heartbeatTimer) {
            // @ts-ignore
            clearInterval(heartbeatTimer);
            heartbeatTimer = null;
        }
    };
    const onError = (err) => {
        if (maxRetry > 0) {
            maxRetry -= 1;
            stop();
            setTimeout(() => {
                start();
            }, 3e3);
        }
        else {
            client.emit("error", err);
            client.emit("error", new Error("重连次数过多，停止重连"));
        }
    };
    const onMessage = (message) => {
        if (typeof message != "object" || message == null || !("type" in message)) {
            console.warn("Unexpected message format", { message });
            return;
        }
        client.emit("message", 
        // TODO: 不太好验证 schema，先强制转了
        message);
    };
    const start = () => {
        if (ws != null)
            return;
        ws = new WebSocket(getRandomPortWSURL());
        coder = new BufferCoder();
        ws.binaryType = "arraybuffer";
        ws.on("open", onOpen);
        ws.on("error", onError);
        ws.on("close", onClose);
        ws.on("message", (data) => {
            if (!(data instanceof ArrayBuffer)) {
                throw new Error("Do not meet the types of ws.binaryType expected");
            }
            coder.decode(data, (messageText) => {
                try {
                    const message = STT.deserialize(messageText);
                    // @ts-ignore
                    if (message?.type === "comm_chatmsg" && message?.chatmsg) {
                        // @ts-ignore
                        message.chatmsg = STT.deserialize(message?.chatmsg);
                    }
                    onMessage(message);
                }
                catch (error) {
                    client.emit("error", error);
                }
            });
        });
    };
    const stop = () => {
        if (ws == null)
            return;
        onClose();
        ws = null;
    };
    if (!opts.notAutoStart) {
        start();
    }
    const client = {
        // @ts-ignore
        ...mitt(),
        start,
        stop,
        send,
    };
    return client;
}
function getRandomPortWSURL() {
    const port = 8500 + ((min, max) => Math.floor(Math.random() * (max - min + 1) + min))(1, 6);
    return `wss://danmuproxy.douyu.com:${port}/`;
}
