/** Global payment modal: order summary, Monnify inline checkout, verify + poll. */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { MONNIFY_API_KEY, MONNIFY_CONTRACT_CODE } from "../config";
import { fetchOrder, verifyOrder } from "../lib/api";
import { paymentEvents } from "../lib/paymentEvents";
import { paymentStore } from "../lib/paymentStore";
import { purchasesStore } from "../lib/purchasesStore";
import { formatNaira } from "../utils/format";

const INITIAL_POLL_DELAYS = [0, 2000, 4000, 8000];
const FOLLOW_UP_POLL_DELAY = 5000;
const MAX_POLL_ATTEMPTS = 24;
const TERMINAL_STATUSES = new Set(["verified", "rejected"]);

const CloseIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path
      d="M18 6L6 18M6 6l12 12"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const CheckIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
    <path
      d="M20 6L9 17l-5-5"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default function PaymentModal() {
  const [open, setOpen] = useState(paymentStore.getState().isOpen);
  const [paymentData, setPaymentData] = useState(
    paymentStore.getState().paymentData,
  );
  const [status, setStatus] = useState("idle");
  const [statusNote, setStatusNote] = useState(null);
  const [verifiedOrder, setVerifiedOrder] = useState(null);

  const pollTimeoutRef = useRef(null);
  const terminalHandledRef = useRef(false);
  const wasOpenRef = useRef(false);
  const statusRef = useRef("idle");

  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  useEffect(() => {
    const unsubscribe = paymentStore.subscribe((state) => {
      setOpen(state.isOpen);
      setPaymentData(state.paymentData);
    });
    return unsubscribe;
  }, []);

  const stopPolling = useCallback(() => {
    if (pollTimeoutRef.current) {
      window.clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
  }, []);

  useEffect(() => {
    const justOpened = open && !wasOpenRef.current;
    wasOpenRef.current = open;
    if (justOpened) {
      stopPolling();
      terminalHandledRef.current = false;
      setStatus("idle");
      setStatusNote(null);
      setVerifiedOrder(null);
    }
    if (!open) {
      stopPolling();
    }
  }, [open, stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  const closeModal = useCallback(() => {
    stopPolling();
    paymentEvents.closePaymentModal();
  }, [stopPolling]);

  const handleTerminalStatus = useCallback(
    (order) => {
      if (terminalHandledRef.current) return;
      terminalHandledRef.current = true;
      stopPolling();

      if (order.status === "verified") {
        setStatus("verified");
        setStatusNote("Payment verified. Your order is confirmed.");
        setVerifiedOrder(order);
        // Match by product name so the in-chat card can flip to a bought
        // state without any backend change. The fetched order carries
        // product_name; record it alongside the single-use reference.
        const productName = order.product_name ?? null;
        if (productName) {
          purchasesStore.add(productName, order.reference);
        }
        window.dispatchEvent(
          new CustomEvent("order-verified", {
            detail: { reference: order.reference, productName },
          }),
        );
      } else {
        setStatus("rejected");
        setStatusNote(
          "We could not verify this payment. Please try again or contact support.",
        );
      }
    },
    [stopPolling],
  );

  const pollOrderStatus = useCallback(
    async (reference, attempt = 0) => {
      if (!reference) return;

      const scheduleNext = () => {
        if (attempt >= MAX_POLL_ATTEMPTS) {
          stopPolling();
          setStatus("pending");
          setStatusNote(
            "We could not confirm this payment yet. It may still complete; check back shortly.",
          );
          return;
        }
        const delay = INITIAL_POLL_DELAYS[attempt] ?? FOLLOW_UP_POLL_DELAY;
        pollTimeoutRef.current = window.setTimeout(() => {
          pollOrderStatus(reference, attempt + 1);
        }, delay);
      };

      try {
        const order = await fetchOrder(reference);
        if (TERMINAL_STATUSES.has(order?.status)) {
          handleTerminalStatus(order);
          return;
        }
        setStatus("pending");
        setStatusNote("Waiting for payment confirmation from Monnify...");
        scheduleNext();
      } catch {
        scheduleNext();
      }
    },
    [handleTerminalStatus, stopPolling],
  );

  const startVerification = useCallback(
    async (reference) => {
      setStatus("verifying");
      setStatusNote("Confirming your payment with Monnify...");
      try {
        const order = await verifyOrder(reference);
        if (TERMINAL_STATUSES.has(order?.status)) {
          handleTerminalStatus(order);
          return;
        }
      } catch {
        /* fall through to polling; verify may race the webhook */
      }
      pollOrderStatus(reference, 0);
    },
    [handleTerminalStatus, pollOrderStatus],
  );

  const handlePay = useCallback(() => {
    if (!paymentData) return;

    if (!window.MonnifySDK) {
      setStatus("error");
      setStatusNote(
        "Monnify checkout is unavailable. Check your connection and reload.",
      );
      return;
    }

    if (!MONNIFY_API_KEY || !MONNIFY_CONTRACT_CODE) {
      setStatus("error");
      setStatusNote(
        "Monnify keys are not configured. Set VITE_MONNIFY_API_KEY and VITE_MONNIFY_CONTRACT_CODE.",
      );
      return;
    }

    const reference = paymentData.reference;
    setStatus("paying");
    setStatusNote("Complete the payment in the Monnify popup.");

    window.MonnifySDK.initialize({
      amount: Number(paymentData.amount),
      currency: paymentData.currency || "NGN",
      reference,
      customerFullName: paymentData.customerFullName,
      customerEmail: paymentData.customerEmail,
      apiKey: MONNIFY_API_KEY,
      contractCode: MONNIFY_CONTRACT_CODE,
      paymentDescription: paymentData.description,
      onComplete: () => {
        startVerification(reference);
      },
      onClose: () => {
        if (statusRef.current === "paying") {
          setStatus("cancelled");
          setStatusNote("Checkout closed before payment completed.");
        }
      },
    });
  }, [paymentData, startVerification]);

  if (!open || !paymentData) return null;

  const isBusy = status === "paying" || status === "verifying";
  const isVerified = status === "verified";
  const amountLabel = formatNaira(paymentData.amount, paymentData.currency);

  const payLabel =
    status === "paying"
      ? "Waiting for Monnify..."
      : status === "verifying"
        ? "Verifying payment..."
        : status === "rejected" || status === "cancelled" || status === "error"
          ? "Try again"
          : `Pay ${amountLabel}`;

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 p-4"
      onClick={closeModal}
    >
      <div
        className="w-full max-w-md rounded-2xl bg-white px-6 py-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line pb-3">
          <h2 className="text-lg font-semibold text-ink">
            {isVerified ? "Payment verified" : "Complete your order"}
          </h2>
          <button
            onClick={closeModal}
            className="rounded-full p-1 text-ink-muted transition-colors hover:bg-surface-alt"
            aria-label="Close payment modal"
          >
            <CloseIcon />
          </button>
        </div>

        {isVerified ? (
          <div className="flex flex-col items-center py-8 text-center">
            <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-success/10 text-success">
              <CheckIcon />
            </div>
            <p className="text-base font-semibold text-ink">Payment verified</p>
            <p className="mt-1 text-sm text-ink-muted">
              Reference {paymentData.reference}
            </p>
            {verifiedOrder?.eta ? (
              <p className="mt-2 text-sm font-medium text-ink-body">
                Estimated arrival: {verifiedOrder.eta}
              </p>
            ) : null}
            <button
              onClick={closeModal}
              className="mt-6 w-full rounded-lg bg-brand py-3 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
            >
              Done
            </button>
          </div>
        ) : (
          <>
            <div className="my-5 text-center">
              <div className="text-3xl font-bold text-ink-body">
                {amountLabel}
              </div>
              <p className="mt-2 text-sm text-ink-muted">
                {paymentData.description}
              </p>
            </div>

            <div className="mb-5 rounded-lg border border-line bg-surface p-4 text-sm">
              <div className="flex justify-between py-1">
                <span className="text-ink-muted">Reference</span>
                <span className="font-medium text-ink-body">
                  {paymentData.reference}
                </span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-ink-muted">Customer</span>
                <span className="font-medium text-ink-body">
                  {paymentData.customerFullName}
                </span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-ink-muted">Email</span>
                <span className="font-medium text-ink-body">
                  {paymentData.customerEmail}
                </span>
              </div>
            </div>

            {statusNote && (
              <div
                className={`mb-4 rounded-lg border px-4 py-3 text-sm ${
                  status === "rejected" || status === "error"
                    ? "border-danger/30 bg-danger/5 text-danger"
                    : "border-line bg-surface text-ink-body"
                }`}
              >
                {statusNote}
              </div>
            )}

            <button
              onClick={handlePay}
              disabled={isBusy}
              className="w-full rounded-lg bg-brand py-3 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:cursor-not-allowed disabled:bg-line-strong"
            >
              {payLabel}
            </button>

            <p className="mt-3 pb-1 text-center text-xs text-ink-muted">
              Secured by Monnify sandbox. No real money moves.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
