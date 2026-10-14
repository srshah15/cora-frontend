// This file defines TypeScript interfaces for protocol-related data structures.

export interface ProtocolInfo {
    protocol_num: string | null;
    title: string | null;
    short_title: string | null;
    product: string | null;
    sponsor: string | null;
    date: string | null;
};

export interface Visit {
    name: string | null;
    timing: string | null;
    procedures: string[] | null;
};

export interface OperationalPlan {
    protocol: ProtocolInfo | null;
    visits: Visit[] | null;
}