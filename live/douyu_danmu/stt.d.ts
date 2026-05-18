export declare namespace STT {
    function escape(v: string): string;
    function unescape(v: string): string;
    function serialize(obj: unknown): string;
    function deserialize(raw: string): unknown;
}
