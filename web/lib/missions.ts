/**
 * Missions, client side: types mirroring backend `harness/db/missions.view` and
 * `harness/missions/report.summary`, and the calls the /missions pages make.
 */
import { json, type Refusal } from "@/lib/brands"
import type { Idea } from "@/lib/business"

export type StepState = "todo" | "done" | "waiting" | "skipped" | "failed"
export type Step = { key: string; label: string; state: StepState; note: string; at: string | null }
export type Outcome = { actual: number; expected: number; lift: number; lift_pct: number; verdict: "worked" | "helped" | "no_effect" }
export type Mission = {
  id: number; kind: string; business_id: number | null; target_day: string
  status: "active" | "waiting" | "done" | "cancelled" | "expired"
  steps: Step[]; done: number; total: number; created_at: string | null; updated_at: string | null
  data: {
    business_name?: string; weekday?: string; brand_id?: number | null; post_id?: number | null; files?: string[]
    forecast?: { value: number; low: number | null; high: number | null; typical: number | null }
    idea?: Idea & { track_note?: string }; share_text?: string
    approved?: boolean; auto?: boolean; undone?: boolean; outcome?: Outcome; trust_offer?: boolean; trust_answered?: boolean
  }
  can_undo?: boolean; trust?: Trust; trust_after?: number
}
export type Trust = { scope: string; streak: number; auto: boolean; offered: boolean; business_id?: number; business_name?: string; trust_after?: number }
export type Report = {
  month: string; label: string; spotted: number; went_ahead: number; on_their_own: number; measured: number; worked: number
  lift: number; price: string | null; best: { mission_id: number; idea: string; day: string; business: string; lift: number } | null
}
export type Listing = { allowed: boolean; missions: Mission[]; trust: Trust[]; this_month: Report; last_month: Report }

const send = (url: string, method: string, body?: unknown) =>
  fetch(url, { method, headers: body === undefined ? undefined : { "Content-Type": "application/json" },
               body: body === undefined ? undefined : JSON.stringify(body) }).catch(() => null)

export const missionsApi = {
  list: () => fetch("/api/missions", { cache: "no-store" }).catch(() => null).then((r) => json<Listing>(r)),
  get: (id: number) => fetch(`/api/missions/${id}`, { cache: "no-store" }).catch(() => null).then((r) => json<Mission>(r)),
  decide: (id: number, decision: "approve" | "reject") =>
    send(`/api/missions/${id}/decide`, "POST", { decision }).then((r) => json<Mission & { message: string }>(r)),
  undo: (id: number) => send(`/api/missions/${id}/undo`, "POST").then((r) => json<Mission>(r)),
  setTrust: (businessId: number, auto: boolean) => send(`/api/missions/trust/${businessId}`, "PUT", { auto }).then((r) => json<Trust>(r)),
}

export const rupees = (n: number) => `₹${Math.round(Math.abs(n)).toLocaleString("en-IN")}`
export type { Refusal }
