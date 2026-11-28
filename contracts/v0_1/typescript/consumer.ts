// Compile-time checks that the generated types give a frontend what it needs.
// Nothing here runs. `api.d.ts` is generated from ../openapi.yaml.
// Each @ts-expect-error line must fail to type-check, or the build fails.
import type { components, paths } from "./api";

type S = components["schemas"];

// True only if A and B accept exactly the same values (distribution disabled).
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
type Expect<T extends true> = T;
type IsAny<T> = 0 extends 1 & T ? true : false;

function never(value: never): never {
  throw new Error(String(value));
}

// Field states are a discriminated union (M-10).
export type QuantityStates = Expect<
  Same<
    S["QuantityField"]["state"],
    "extracted" | "missing" | "ambiguous" | "employee_entered" | "employee_cleared"
  >
>;
export type NotAny = Expect<Same<IsAny<S["QuantityField"]>, false>>;

export function describeQuantity(field: S["QuantityField"]): string {
  switch (field.state) {
    case "extracted": {
      const value: string = field.value;
      return `proposed ${value}`;
    }
    case "missing": {
      const value: null = field.value;
      return `not stated ${value}`;
    }
    case "ambiguous": {
      const choices: string[] = field.candidates;
      const reason: S["AmbiguityReason"] = field.ambiguity_reason;
      return `${reason}: ${choices.join(" or ")}`;
    }
    case "employee_entered": {
      const who: S["PersonRef"] = field.entered_by; // M-1
      return `${field.value} entered by ${who.display_name}`;
    }
    case "employee_cleared":
      return `cleared by ${field.cleared_by.display_name}`;
    default:
      return never(field);
  }
}

export function unsafeRead(field: S["QuantityField"]): string {
  // @ts-expect-error a value is not a string until the state has been checked
  return field.value;
}

// The AI proposal stays readable after an employee decision (M-4).
export function proposalState(field: S["TextField"]): string | undefined {
  return field.proposal?.state;
}

// Every line and job field keeps its own union.
export type LineQuantity = Expect<Same<S["MaterialLine"]["quantity"], S["QuantityField"]>>;
export type Fulfillment = Expect<
  Same<
    Extract<S["JobDetails"]["fulfillment_method"], { state: "extracted" }>["value"],
    "delivery" | "pickup"
  >
>;

// Closed unit list and no send action.
export type Units = Expect<
  Same<
    S["UnitCode"],
    | "piece"
    | "sheet"
    | "linear_foot"
    | "board_foot"
    | "bundle"
    | "box"
    | "bag"
    | "roll"
    | "pallet"
  >
>;
export type Decisions = Expect<
  Same<S["DecisionRequest"]["action"], "approve_internal" | "decline" | "reopen">
>;
export type Handling = Expect<Same<S["HandlingRequest"]["action"], "mark_handled" | "reopen">>;

// Request bodies: server defaults stay optional for the client.
export const approve: S["DecisionRequest"] = {
  action: "approve_internal",
  expected_version: 2,
  acknowledged_warning_ids: [],
};
export const handled: S["HandlingRequest"] = {
  action: "mark_handled",
  expected_handling_version: 0,
  reason: "not_a_request",
};
export const edit: S["RequestEdit"] = {
  expected_version: 1,
  operations: [
    { op: "set_dimensions", line_id: "id", text: "2x6x10" },
    { op: "choose_candidate", target: { scope: "line", line_id: "id", field: "quantity" }, candidate_index: 1 },
    { op: "clear_field", target: { scope: "job_detail", field: "notes" } },
    { op: "restore_line", line_id: "id" },
  ],
};
export const sendIsImpossible: S["DecisionRequest"] = {
  // @ts-expect-error there is no send decision
  action: "send",
  expected_version: 2,
};
export const nullValueIsImpossible: S["SetQuantity"] = {
  op: "set_quantity",
  line_id: "id",
  // @ts-expect-error set operations always carry a value
  value: null,
};

export type Operation = S["RequestEdit"]["operations"][number];
export type Operations = Expect<
  Same<
    Operation["op"],
    | "set_text_field"
    | "set_quantity"
    | "set_unit"
    | "set_dimensions"
    | "set_job_text"
    | "set_fulfillment"
    | "clear_field"
    | "choose_candidate"
    | "select_sku"
    | "clear_sku_selection"
    | "add_line"
    | "remove_line"
    | "restore_line"
  >
>;

// Response data the screens need (M-2, M-3, M-6 to M-9, S-1, S-5).
export function inboxRow(item: S["InboxItem"]) {
  return [item.preview, item.updated_at, item.handling.status, item.attention, item.attachment_count] as const;
}
export function attachment(a: S["AttachmentMetadata"]) {
  return [a.filename, a.disposition, a.size_bytes, a.processing] as const;
}
export function selectionNotice(match: S["MatchResult"]) {
  return [match.last_cleared_selection?.reason, match.selection?.current.catalog_stale] as const;
}
export function blocker(b: S["ApprovalBlocker"]) {
  return [b.blocker_id, b.code, b.target.scope, b.target.line_id, b.target.field] as const;
}
export function history(r: S["RevisionSummary"]) {
  return r.changes.map((c) => [c.target.field, c.before?.text, c.after?.text] as const);
}
export function conflict(e: S["ErrorBody"]) {
  const csrf: S["ErrorCode"] = "csrf_failed";
  return [csrf, e.details.map((d) => d.location), e.changed_by?.display_name, e.changed_at] as const;
}
export function counts(c: S["InboxCounts"]) {
  return [c.needs_review, c.failed, c.drafts] as const;
}
export function failure(s: S["CommunicationStatus"]) {
  return [s.failure_code, s.employee_message, s.attempt_count, s.next_retry_at] as const;
}

// Routes.
type RequestPath = paths["/api/v1/yards/{yard_id}/requests/{request_id}"];
export type RequestBody = Expect<
  Same<RequestPath["get"]["responses"][200]["content"]["application/json"], S["RequestDetail"]>
>;
export type NoAttachmentDownload = Expect<
  Same<Extract<keyof paths, `${string}attachments${string}`>, never>
>;
export type NoSendRoute = Expect<Same<Extract<keyof paths, `${string}send${string}`>, never>>;
