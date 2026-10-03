"use client"

import { H, LegalPage } from "@/components/hangul/LegalPage"
import { LEGAL } from "@/lib/legal"

/**
 * Privacy Policy. Written from what the code actually does -- what is stored,
 * which services see what, what "delete" means today. If the data handling
 * changes (a new provider, real deletion of chats), change this page with it.
 */
export default function PrivacyPage() {
  const { product, operator, contactEmail, minimumAge } = LEGAL
  return (
    <LegalPage title="Privacy Policy"
      intro={`This policy explains what ${product} collects, why, who it is shared with, and the choices you have. ${product} is operated by ${operator}. If anything here is unclear, write to ${contactEmail}.`}>

      <H>What we collect</H>
      <ul>
        <li><b>Your account:</b> your name, email address and profile picture from the way you sign in (Google or an email link).</li>
        <li><b>What you ask and what you add:</b> your messages and the assistant&apos;s replies, files and photos you upload (and the text extracted from them), voice notes you upload, and the reminders, lists, notes, memories and scheduled tasks you create.</li>
        <li><b>Voice:</b> when you talk to {product}, the recording is sent to be turned into text and is <b>not stored</b>; only the text of your message is kept, like a typed message. Voice notes you choose to upload are stored as files.</li>
        <li><b>Your preferences:</b> the name you want to be called, your city, timezone (taken from your device unless you set one), tone, language and custom instructions.</li>
        <li><b>Connected apps:</b> if you connect Google, GitHub, Notion or Slack, {product} reads from them only when a request needs it (for example, your calendar when you ask what&apos;s on today), and writes to them only after you approve each action.</li>
        <li><b>Billing:</b> your plan, its status and renewal date, and a record of usage and credits. Payments are handled by Dodo Payments; <b>we never see or store your card details</b>.</li>
        <li><b>Technical records:</b> server logs (which can include the text of a request) and an audit log of the actions the assistant takes and security checks it runs, with passwords, tokens and keys removed. We keep these for security, debugging and abuse prevention.</li>
      </ul>

      <H>How we use it</H>
      <ul>
        <li>To answer your requests and do the things you ask (set reminders, draft emails, create files…).</li>
        <li>To remember context you&apos;ve shared, so later answers fit you.</li>
        <li>To send you the emails you ask for (reminders, your morning brief) and essential account messages.</li>
        <li>To run billing, enforce plan limits and prevent abuse and security threats.</li>
      </ul>
      <p><b>We do not sell your data, use it for advertising, or use your content to train AI models.</b></p>

      <H>Who we share it with</H>
      <p>Only the services needed to provide {product}, and only what each one needs:</p>
      <ul>
        <li><b>OpenAI</b> — runs the AI models that read your request and write the answer, and turns speech into text and text into speech. Under OpenAI&apos;s API terms, this data is not used to train their models by default and may be kept by them for a limited period for abuse monitoring.</li>
        <li><b>Google</b> — sign-in, and Gmail, Calendar, Drive, Docs, Sheets and Contacts if you connect them.</li>
        <li><b>GitHub, Notion, Slack</b> — only if you connect them.</li>
        <li><b>Dodo Payments</b> — processes payments as our merchant of record.</li>
        <li><b>Resend</b> — delivers the emails you ask for.</li>
        <li><b>Tavily</b> — receives web search queries when the assistant searches the web.</li>
        <li><b>OpenStreetMap services, Open-Meteo and Frankfurter</b> — receive place names, cities or currency codes for maps, weather and currency conversions (not your account details).</li>
        <li><b>Our hosting and database providers</b>, who store and run the service for us.</li>
        <li>Authorities, where the law requires it.</li>
      </ul>

      <H>Google user data</H>
      <p>
        {product}&apos;s use and transfer to any other app of information received from Google APIs will adhere to the{" "}
        <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank" rel="noopener noreferrer">Google API Services User Data Policy</a>,
        including the Limited Use requirements. In particular, Google user data is used only to provide the features you ask for, is not
        used for advertising, is not sold, is not used to train generalised AI models, and is not read by people unless you ask us to (for
        support), it is needed for security, or the law requires it.
      </p>

      <H>How we protect it</H>
      <ul>
        <li>Tokens you give us for GitHub, Notion and Slack are encrypted, and the assistant never sees them: requests are made on your behalf by a separate component that adds the token at the last moment.</li>
        <li>Google sign-in tokens are kept in our database, accessible only to the service.</li>
        <li>Each person&apos;s files and data are kept separate, and the assistant can only reach your own.</li>
        <li>Anything that sends, posts, changes or deletes something on your behalf waits for your approval.</li>
        <li>Connections are encrypted (https).</li>
      </ul>
      <p>No system is perfectly secure; if a breach affects your data we will tell you as the law requires.</p>

      <H>How long we keep it, and deleting it</H>
      <ul>
        <li>Your data is kept while your account is open.</li>
        <li>Deleting a chat hides it from you and from the assistant immediately; a copy stays in our database until your account is deleted.</li>
        <li>You can delete reminders, list items, notes and memories yourself at any time.</li>
        <li>To delete your account and everything in it, email <a href={`mailto:${contactEmail}`}>{contactEmail}</a> from your account&apos;s email address. We do it within 30 days, except records we must keep by law (for example, payment records).</li>
        <li>You can disconnect Google, GitHub, Notion or Slack at any time under Connected apps; you can also remove {product}&apos;s access from your Google account&apos;s security settings.</li>
      </ul>

      <H>Your rights</H>
      <p>
        Depending on where you live (for example under India&apos;s Digital Personal Data Protection Act or the EU/UK GDPR), you may have the
        right to access, correct, export or delete your personal data, to withdraw consent, and to complain to a regulator. Email{" "}
        <a href={`mailto:${contactEmail}`}>{contactEmail}</a> and we will respond within 30 days.
      </p>

      <H>Children</H>
      <p>{product} is not for children under {minimumAge} (or the minimum age for consent to online services where you live). If you believe a child has given us data, contact us and we will delete it.</p>

      <H>International transfers</H>
      <p>The services we use may process data in other countries, including the United States. We use providers that protect data with appropriate safeguards.</p>

      <H>Changes</H>
      <p>If we change this policy in a way that matters, we will tell you in the app or by email before it takes effect.</p>

      <H>Contact</H>
      <p>{operator} · {LEGAL.address} · <a href={`mailto:${contactEmail}`}>{contactEmail}</a></p>
    </LegalPage>
  )
}
