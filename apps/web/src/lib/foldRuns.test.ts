import { describe, expect, it } from "vitest";
import { foldRuns } from "./foldRuns";
import type { Message } from "./types";
import { run } from "@/test/fixtures";
import { ROOM_A } from "@/test/fakeWebSocket";

const RUN = `run_${"1".repeat(32)}`;
const OLD = `run_${"2".repeat(32)}`;
const REPLY = `run_${"3".repeat(32)}`;

function m(seq: number, over: Partial<Message> = {}): Message {
  return {
    id: `msg_${String(seq).padStart(32, "0")}`,
    protocol: "ccmp/1",
    seq,
    room_id: ROOM_A,
    sender: { principal_id: "usr_x", kind: "owner", display_name: "Noel" },
    kind: "chat",
    body: { text: `m${seq}` },
    created_at: "2026-11-03T06:00:00Z",
    ...over,
  };
}
const coord = (seq: number, runId: string, kind: Message["kind"] = "task.assign") =>
  m(seq, {
    kind,
    correlation_id: runId,
    sender: { principal_id: "sys_x", kind: "system", display_name: "Coordinator" },
  });
const agentMsg = (seq: number, runId: string) =>
  m(seq, { correlation_id: runId, sender: { principal_id: "agt_x", kind: "agent", display_name: "Claude" } });

describe("foldRuns", () => {
  const messages = [
    m(1),
    coord(2, RUN),
    agentMsg(3, RUN),
    m(4),
    coord(5, RUN, "task.result"),
    agentMsg(6, REPLY),
    coord(7, OLD),
    agentMsg(8, OLD),
    m(9, {
      correlation_id: RUN,
      sender: { principal_id: "sys_x", kind: "system", display_name: "Coordinator" },
      body: { text: "Owner APPROVED: x", data: { decision_id: "dec_1" } },
    }),
  ];

  it("folds finished workflow runs where they started and keeps everything else", () => {
    const items = foldRuns(messages, [
      run({ id: RUN, status: "completed" }),
      run({ id: REPLY, kind: "reply", status: "completed" }),
    ]);
    expect(
      items.map((i) => (i.type === "run" ? `run:${i.runId.slice(4, 5)}:${i.messages.length}` : i.message.seq)),
    ).toEqual([1, "run:1:3", 4, 6, "run:2:2", 9]);
    const old = items.find((i) => i.type === "run" && i.runId === OLD);
    expect(old?.type === "run" && old.run).toBeNull();
  });

  it("leaves active runs open and hides archived ones", () => {
    const active = foldRuns(messages, [run({ id: RUN, status: "running" })]);
    expect(active.filter((i) => i.type === "message").map((i) => (i.type === "message" ? i.message.seq : 0))).toContain(
      2,
    );
    const archived = foldRuns(messages, [run({ id: RUN, status: "completed", archived_at: "2026-11-03T06:30:00Z" })]);
    expect(archived.some((i) => i.type === "run" && i.runId === RUN)).toBe(false);
    expect(archived.some((i) => i.type === "message" && i.message.seq === 3)).toBe(false);
  });
});
