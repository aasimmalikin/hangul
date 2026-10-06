import { userProxy } from "../../_user"

export const runtime = "nodejs"

/** GET: is WhatsApp linked? POST: a fresh code to send from WhatsApp. DELETE: unlink. */
export async function GET(req: Request) { return userProxy(req, "/whatsapp/link", { method: "GET" }) }
export async function POST(req: Request) { return userProxy(req, "/whatsapp/link", { method: "POST" }) }
export async function DELETE(req: Request) { return userProxy(req, "/whatsapp/link", { method: "DELETE" }) }
