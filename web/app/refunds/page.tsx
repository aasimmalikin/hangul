"use client"

import { H, LegalPage } from "@/components/hangul/LegalPage"
import { LEGAL } from "@/lib/legal"

/** Refund Policy (payments go through Dodo Payments, the merchant of record). */
export default function RefundsPage() {
  const { product, contactEmail, refundWindowDays: days } = LEGAL
  return (
    <LegalPage title="Refund Policy"
      intro={`We want ${product} to be worth paying for. Payments are processed by Dodo Payments, our merchant of record, so refunds go back through them to your original payment method.`}>

      <H>Cancelling a subscription</H>
      <ul>
        <li>Cancel any time under <i>You → Plan &amp; billing → Manage subscription</i>. Nothing more is charged after that.</li>
        <li>You keep your paid plan until the end of the billing period you&apos;ve already paid for; after that your account moves to the free plan.</li>
      </ul>

      <H>Refunds on subscriptions</H>
      <ul>
        <li><b>First payment:</b> if {product} isn&apos;t right for you, ask within {days} days of your first payment for a plan and we&apos;ll refund it in full, as long as you haven&apos;t used most of that period&apos;s included usage.</li>
        <li><b>Renewals:</b> renewal payments are generally not refunded, but if you forgot to cancel and haven&apos;t used the new period, write to us within {days} days of the renewal and we&apos;ll look at it.</li>
        <li>We don&apos;t give partial refunds for the unused part of a period, except where the law requires it.</li>
      </ul>

      <H>Credits</H>
      <ul>
        <li>Unused credits can be refunded within {days} days of purchase.</li>
        <li>Credits that have been used are not refundable.</li>
      </ul>

      <H>Mistakes and problems</H>
      <ul>
        <li>Charged twice, or charged after you cancelled? We&apos;ll refund the extra charge in full.</li>
        <li>If a serious problem on our side stopped you from using {product} for a long period, contact us and we&apos;ll make it right.</li>
      </ul>

      <H>How to ask</H>
      <p>
        Email <a href={`mailto:${contactEmail}`}>{contactEmail}</a> from the address on your account, with the date of the payment. We reply
        within 3 business days. Approved refunds are sent through Dodo Payments and usually reach you within 5–10 business days, depending
        on your bank.
      </p>
      <p>Please contact us before disputing a charge with your bank — it&apos;s usually faster, and a chargeback can suspend your account while it&apos;s investigated.</p>

      <H>Your legal rights</H>
      <p>This policy doesn&apos;t affect any rights you have under the consumer law of the country you live in.</p>
    </LegalPage>
  )
}
