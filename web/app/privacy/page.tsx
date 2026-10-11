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
        <li><b>Pre-registration:</b> if you pre-register before launch, your email address and, if you choose them, the kind of business you run, your city and which plan interests you, plus the site that sent you (for example X). We use it only to email you at launch about your founding-member perks.</li>
        <li><b>What you ask and what you add:</b> your messages and the assistant&apos;s replies, files and photos you upload (and the text extracted from them), voice notes you upload, and the reminders, lists, notes, memories and scheduled tasks you create.</li>
        <li><b>Voice:</b> when you talk to {product}, the recording is sent to be turned into text and is <b>not stored</b>; only the text of your message is kept, like a typed message. Voice notes you choose to upload are stored as files.</li>
        <li><b>WhatsApp:</b> if you link it, your WhatsApp number and when you last messaged {product} (WhatsApp only lets us reply freely for 24 hours after that). Your WhatsApp messages are kept like any other conversation.</li>
        <li><b>Notifications:</b> if you turn them on for a phone or computer, the address your browser gives us for sending to it (and the keys that encrypt what we send), plus the kind of browser. Turning them off, or removing the app, deletes it.</li>
        <li><b>Your morning check-in:</b> if you answer &ldquo;How are you feeling today?&rdquo; on your home screen, the answer (great, okay, tired or swamped) is kept with the date, to count the mornings you&apos;ve checked in and to keep that day&apos;s plans lighter or shorter. You never have to answer.</li>
        <li><b>Brands:</b> if you set one up, its name, colours, style, writing voice and font, and the logo you upload (kept as a file in your folder), so what {product} makes for you follows it. Adding your words, logo and sizes to a picture happens on our own servers. Removing a brand hides it and stops it being used, but, like a deleted chat, its record and logo file are kept until you delete your account.</li>
        <li><b>Launch plans:</b> your answers (what you want to start, where, how big, your budget), the checklist and the numbers you edit.</li>
        <li><b>Customers:</b> the customers you add to your list (their name and, if you add them, phone number, birthday and a short note) and how often they come in. You add them; you are responsible for having your customers&apos; agreement to keep their details, and we keep them only to show them to you. Hangul never contacts your customers: a birthday wish or a &ldquo;we miss you&rdquo; message is drafted for you to send yourself. Removing a customer hides them; their details are kept until you delete your account.</li>
        <li><b>Photos of your sales:</b> when you send a photo of a bill book page or a day-end report to log your sales, the photo is kept in your files and sent to OpenAI to read the total, like any image you upload.</li>
        <li><b>How&apos;s business:</b> each business you add (its name, kind and city), the daily sales and bill counts you log or import, and that day&apos;s weather. Spreadsheets you import are read for the date and amount of each sale and are not kept; only the daily totals are. The forecast and the ideas are worked out on our own servers from your figures alone: your sales are never shared, compared with other businesses, or used to train anything. Removing a business hides it; its days are kept until you delete your account.</li>
        <li><b>Brand Studio:</b> the photos you add to a brand&apos;s library and the posts you make are kept as files in your folder, with each post&apos;s words, captions and review status. Making posts happens on our own servers; only writing captions (the post&apos;s words and your brand&apos;s name, voice and hashtags) and improving a photo with AI send anything to OpenAI.</li>
        <li><b>Client review links:</b> if you create one, anyone who has the link can see that one post (its images, captions and your brand&apos;s name and logo) and approve it or ask for changes, without an account, until the link expires (14 days). What they type, and the name they give, is saved with the post.</li>
        <li><b>Your preferences:</b> the name you want to be called, your city, timezone (taken from your device unless you set one), tone, language and custom instructions.</li>
        <li><b>Connected apps:</b> if you connect Google, {product} reads from them when a request needs it (for example, your calendar when you ask what&apos;s on today) and for the Your word feature below, and writes to them only after you approve each action.</li>
        <li><b>Your word (promises):</b> {product} keeps the promises you tell it about, and the ones it finds, as short lines (what was promised, by whom, by when, and the sentence it came from). On Plus and Pro, if Gmail is connected, it reads mail you sent and received in the last day or two about every half hour, sends the new part of each personal email (not newsletters or automated mail) to our AI provider to find promises, and keeps only the promises, never the email itself. You can turn this off in Settings → Your word. If Calendar is connected, it checks for meetings that just ended so it can ask what was promised. Nothing is sent to anyone without your OK.</li>
        <li><b>Google Meet (Plus and Pro):</b> if you connect it, {product} can make a meeting link when you ask, and read your past calls (when they were, who joined) and, where Google made one, a call&apos;s transcript — only when you ask about that call. The transcript is read for that answer and not stored separately; like any message, it is sent to our AI provider to write the answer and may appear in your chat.</li>
        <li><b>Billing:</b> your plan, its status and renewal date, and a record of usage and credits. Payments are handled by Dodo Payments; <b>we never see or store your card details</b>.</li>
        <li><b>Technical records:</b> server logs (which can include the text of a request) and an audit log of the actions the assistant takes and security checks it runs, with passwords, tokens and keys removed. We keep these for security, debugging and abuse prevention.</li>
      </ul>

      <H>How we use it</H>
      <ul>
        <li>To answer your requests and do the things you ask (set reminders, draft emails, create files…).</li>
        <li>To remember context you&apos;ve shared, so later answers fit you.</li>
        <li>To suggest what you usually ask at this time of day when you tap the stag on your home screen. This is worked out from your own messages of the last 30 days each time you open the app; nothing extra is stored and it never leaves {product}.</li>
        <li>To send you the emails you ask for (reminders, your morning brief) and essential account messages.</li>
        <li>To run billing, enforce plan limits and prevent abuse and security threats.</li>
      </ul>
      <p><b>We do not sell your data, use it for advertising, or use your content to train AI models.</b></p>

      <H>Who we share it with</H>
      <p>Only the services needed to provide {product}, and only what each one needs:</p>
      <ul>
        <li><b>OpenAI</b> — runs the AI models that read your request and write the answer, turns speech into text and text into speech, and makes or changes images you ask for: when you ask {product} to edit a photo, that photo is sent to OpenAI, along with your brand&apos;s style if one is on. Under OpenAI&apos;s API terms, this data is not used to train their models by default and may be kept by them for a limited period for abuse monitoring.</li>
        <li><b>Google</b> — sign-in, and Gmail, Calendar, Drive, Docs, Sheets, Contacts and Meet if you connect them.</li>
        <li><b>Dodo Payments</b> — processes payments as our merchant of record.</li>
        <li><b>Resend</b> — delivers the emails you ask for.</li>
        <li><b>Your browser&apos;s notification service</b> (Google for Chrome and Android, Apple for Safari and iPhone, Mozilla for Firefox, Microsoft for Edge on Windows) — only if you turn notifications on: it carries your reminders and brief to your device. They are encrypted so that service can&apos;t read them.</li>
        <li><b>Meta (WhatsApp)</b> — only if you link WhatsApp: your WhatsApp number, and the messages, voice notes, photos and files you exchange with {product} there, pass through Meta&apos;s WhatsApp service. Your reminders are sent through it too (on Free, only within 24 hours of your last message), and on Plus and Pro your brief.</li>
        <li><b>Tavily</b> — receives web search queries when the assistant searches the web. A launch plan with live prices sends searches made of the kind of business, the items it needs and your city (not your name, budget or notes).</li>
        <li><b>OpenStreetMap services, Open-Meteo and Frankfurter</b> — receive place names, cities or currency codes for maps, weather and currency conversions (not your account details). If you save a home address, it and the place of your next calendar event are sent to OpenStreetMap&apos;s routing services to work out when to leave. A launch plan with live prices sends your city and area to OpenStreetMap to find suppliers nearby. For How&apos;s business, your business&apos;s city goes to Open-Meteo for its past and coming weather.</li>
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
        <li>You can disconnect Google at any time under Connected apps; you can also remove {product}&apos;s access from your Google account&apos;s security settings.</li>
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
