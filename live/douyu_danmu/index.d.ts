import { Emitter } from "mitt";
interface Message$Chat {
    type: "chatmsg";
    gid: string;
    rid: string;
    uid: string;
    nn: string;
    txt: string;
    cid: string;
    level: string;
    gt: string;
    col: string;
    ct: string;
    rg: string;
    pg: string;
    dlv: string;
    dc: string;
    bdlv: string;
    ic: string;
    cst: string;
}
interface Message$Gift {
    type: "dgb";
    rid: string;
    gid: string;
    gfid: string;
    gs: string;
    uid: string;
    nn: string;
    str: string;
    level: string;
    dw: string;
    gfcnt: string;
    hits: string;
    dlv: string;
    dc: string;
    bdl: string;
    rg: string;
    pg: string;
    rpid: string;
    slt: string;
    elt: string;
    ic: string;
    bnn: string;
    gfn: string;
}
interface Message$ODFBC {
    type: "odfbc";
    uid: string;
    rid: string;
    nick: string;
    price: string;
}
interface Message$RNDFBC {
    type: "rndfbc";
    uid: string;
    rid: string;
    nick: string;
    price: string;
}
interface Message$CommChatPandora {
    type: "comm_chatmsg";
    rid: string;
    vrid: string;
    btype: "pandora";
    range: string;
    cprice: string;
    crealPrice: string;
    cmgType: string;
    gbtemp: string;
    uid: string;
    cet: string;
    now: string;
    csuperScreen: string;
    danmucr: string;
}
interface Message$CommChatVoiceDanmu {
    type: "comm_chatmsg";
    rid: string;
    vrid: string;
    btype: "voiceDanmu";
    range: string;
    cprice: string;
    crealPrice: string;
    cmgType: string;
    gbtemp: string;
    uid: string;
    cet: string;
    now: string;
    csuperScreen: string;
    danmucr: string;
    chatmsg: {
        nn: string;
        bnn: string;
        level: string;
        brid: string;
        ail: string;
        bl: string;
        type: "chatmsg";
        rid: string;
        gag: string;
        uid: string;
        txt: string;
        hidenick: string;
        nc: string;
        ifs: string;
        ic: string;
        nl: string;
        tbid: string;
        tbl: string;
        tbvip: string;
    };
}
type Message$CommChat = Message$CommChatPandora | Message$CommChatVoiceDanmu;
export type Message = Message$Chat | Message$Gift | Message$CommChat | Message$ODFBC | Message$RNDFBC;
export interface DYClient extends Emitter<{
    message: Message;
    error: unknown;
}> {
    start: () => void;
    stop: () => void;
    send: (message: Record<string, unknown>) => void;
}
export declare function createDYClient(channelId: number, opts?: {
    notAutoStart?: boolean;
}): DYClient;
export {};
