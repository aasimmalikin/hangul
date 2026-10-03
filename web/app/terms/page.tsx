"use client"

import Link from "next/link"
import { H, LegalPage } from "@/components/hangul/LegalPage"
import { LEGAL } from "@/lib/legal"

/** Terms of Service: what Hangul is, the rules, AI limits, plans and billing, liability. */
export default function TermsPage() {
  const { product, operator, contactEmail, jurisdiction, minimumAge } = LEGAL
  return (
    <LegalPage title="Terms of Service"
      intro={`These terms are the agreement between you and ${operator} ("we") for using ${product}, a personal AI assistant. By creating an account or using ${product}, you agree to them.`}>

      <H>Your account</H>
      <ul>
        <li>You must be at least {minimumAge} years old (or the minimum age for online services where you live) to use {product}.</li>
        <li>Keep your sign-in secure. You are responsible for what happens under your account.</li>
        <li>Give accurate information, and tell us if you think your account has been misused.</li>
      </ul>

      <H>Using {product}</H>
      <p>Don&apos;t use {product} to:</p>
      <ul>
        <li>break the law, or infringe anyone&apos;s rights (including privacy and intellectual property);</li>
        <li>harass, threaten, deceive or spam people, or send messages they didn&apos;t ask for;</li>
        <li>create content that is illegal, sexually exploits minors, promotes violence, or is designed to mislead;</li>
        <li>try to break, overload, or get around the limits or security of {product} or of the apps you connect;</li>
        <li>attack other people with hidden instructions in documents or links meant to manipulate an AI;</li>
        <li>resell or give others access to your account without our permission.</li>
      </ul>
      <p>We may limit, suspend or close accounts that break these rules.</p>

      <H>About AI answers</H>
      <ul>
        <li>{product} uses AI. Its answers can be wrong, incomplete or out of date. Check anything important.</li>
        <li>It is not a substitute for professional advice (medical, legal, financial, tax or otherwise).</li>
        <li>Weather, maps, travel times and currency rates come from third-party services and may be inaccurate or unavailable.</li>
      </ul>

      <H>Actions on your behalf</H>
      <p>
        {product} can act for you in the apps you connect — sending email, changing your calendar, posting messages, creating files.
        Anything that sends, posts, changes or deletes something waits for you to approve it. <b>You are responsible for the actions you
        approve</b> and for following the terms of the apps you connect (Google, GitHub, Notion, Slack…).
      </p>

      <H>Your content</H>
      <ul>
        <li>You own what you put into {product} and what it creates for you, to the extent the law allows.</li>
        <li>You give us permission to store and process your content only to run {product} for you, as described in our <Link href="/privacy">Privacy Policy</Link>.</li>
        <li>Make sure you have the right to upload what you upload.</li>
      </ul>

      <H>Plans, payments and credits</H>
      <ul>
        <li>{product} has a free plan and paid plans. Each plan includes certain features and a monthly amount of usage; when it&apos;s used up you can upgrade, buy credits, or wait for it to reset.</li>
        <li>Payments are processed by <b>Dodo Payments</b>, our merchant of record, which also handles taxes and invoices.</li>
        <li>Paid plans renew automatically each billing period until you cancel. You can cancel any time under <i>You → Plan &amp; billing → Manage subscription</i>; you keep your plan until the end of the period you&apos;ve paid for.</li>
        <li>Credits don&apos;t expire while your account is open, can&apos;t be transferred, and have no cash value.</li>
        <li>We may change plans, features or prices. We&apos;ll tell you before a price change affects you, and it applies from your next billing period.</li>
        <li>Refunds are covered by our <Link href="/refunds">Refund Policy</Link>.</li>
      </ul>

      <H>Availability and changes</H>
      <p>
        We work to keep {product} running, but it may sometimes be unavailable, and features can change or be removed. Free-plan limits
        may change at any time. Connected apps and third-party services can change or stop working outside our control.
      </p>

      <H>Ending your account</H>
      <p>
        You can stop using {product} and ask us to delete your account at any time ({contactEmail}). We may suspend or end accounts that
        break these terms, or end the service with reasonable notice. Sections about content, disclaimers and liability continue after
        your account ends.
      </p>

      <H>Disclaimers</H>
      <p>
        {product} is provided &quot;as is&quot; and &quot;as available&quot;. To the extent the law allows, we make no promises that it will be
        accurate, uninterrupted or fit for a particular purpose.
      </p>

      <H>Limitation of liability</H>
      <p>
        To the extent the law allows, we are not liable for indirect or consequential losses (such as lost profits or data), and our total
        liability to you for any claim is limited to the amount you paid us in the 12 months before the claim. Nothing in these terms limits
        liability that cannot be limited by law, or your statutory rights as a consumer.
      </p>

      <H>Governing law</H>
      <p>These terms are governed by {jurisdiction}.</p>

      <H>Changes to these terms</H>
      <p>If we change these terms in a way that matters, we&apos;ll tell you in the app or by email before the change applies. Continuing to use {product} after that means you accept the new terms.</p>

      <H>Contact</H>
      <p>{operator} · {LEGAL.address} · <a href={`mailto:${contactEmail}`}>{contactEmail}</a></p>
    </LegalPage>
  )
}
