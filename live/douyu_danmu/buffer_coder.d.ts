export declare class BufferCoder {
    buffer: ArrayBuffer;
    decoder: TextDecoder;
    encoder: TextEncoder;
    littleEndian: boolean;
    readLength: number;
    concat(...buffers: ArrayBuffer[]): Uint8Array;
    decode(newBuffer: ArrayBuffer, callback: (message: string) => void, littleEndian?: boolean): void;
    encode(msg: string, littleEndian?: boolean): ArrayBuffer;
}
