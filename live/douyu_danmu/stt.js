export var STT;
(function (STT) {
    function escape(v) {
        return v.toString().replace(/@/g, "@A").replace(/\//g, "@S");
    }
    STT.escape = escape;
    function unescape(v) {
        return v.toString().replace(/@S/g, "/").replace(/@A/g, "@");
    }
    STT.unescape = unescape;
    function serialize(obj) {
        if (obj == null)
            throw new Error("Cant serialize null value");
        if (Array.isArray(obj)) {
            return obj.map((v) => STT.serialize(v)).join("");
        }
        if (typeof obj === "object") {
            return Object.entries(obj)
                .map(([k, v]) => `${k}@=${STT.serialize(v)}`)
                .join("");
        }
        return STT.escape(obj.toString()) + "/";
    }
    STT.serialize = serialize;
    function deserialize(raw) {
        if (raw.includes("//")) {
            return raw
                .split("//")
                .filter((e) => e !== "")
                .map((item) => STT.deserialize(item));
        }
        if (raw.includes("@=")) {
            return raw
                .split("/")
                .filter((part) => part !== "")
                .reduce((obj, part) => {
                const [key, val] = part.split("@=");
                obj[key] = val ? STT.deserialize(val) : "";
                return obj;
            }, {});
        }
        return STT.unescape(raw);
    }
    STT.deserialize = deserialize;
})(STT || (STT = {}));
