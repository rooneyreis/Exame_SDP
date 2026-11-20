import java.math.BigDecimal;

/** A settlement order sent by the coordinator after a distributed transfer is CONFIRMADA. */
public record SettlementOrder(
        String txId, String fromIban, String toIban,
        BigDecimal amount, String currency,
        BigDecimal convertedAmount, String convertedCurrency,
        String timestamp, String sha256, String signature) {

    /**
     * The canonical content that is hashed (SHA-256) and signed (Ed25519).
     * Both sides build exactly this string, so XML formatting (spaces, attribute
     * order, line breaks) never changes the signature.
     */
    public String canonical() {
        return String.join("|", "SettlementOrder", "1.0", txId, fromIban, toIban,
                amount.toPlainString(), currency, convertedAmount.toPlainString(), convertedCurrency, timestamp);
    }
}
