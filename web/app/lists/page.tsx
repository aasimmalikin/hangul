import { redirect } from "next/navigation"

/** The old "My stuff" address: lists, notes and files now live in Kept's Holding drawer. */
export default function ListsPage() {
  redirect("/kept#holding")
}
