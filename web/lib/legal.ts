/**
 * Everything the legal pages need that only the operator can decide. Fill
 * these in before launch -- the pages read them, so one edit updates all three.
 * The text was drafted from how Hangul actually handles data; it is a starting
 * point, not legal advice. Have a lawyer review it for your jurisdiction.
 */
export const LEGAL = {
  product: "Hangul",
  /** Your legal name, or your company's (e.g. "Aasim Malik" or "Hangul Technologies Pvt Ltd"). */
  operator: "[Operator legal name]",
  /** Postal address for legal notices. */
  address: "[Postal address]",
  contactEmail: "official@hangul.site",
  website: "https://hangul.site",
  /** Courts / law that govern the Terms (e.g. "the laws of India; courts of Pune, Maharashtra"). */
  jurisdiction: "[Governing law and courts]",
  /** Days after a first purchase in which a refund can be asked for. */
  refundWindowDays: 7,
  minimumAge: 13,
  lastUpdated: "3 October 2026",
}

export const PLACEHOLDER = /^\[.*\]$/
