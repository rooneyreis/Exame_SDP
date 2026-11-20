import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Mainframe-style ledger: one FIXED-WIDTH record per line (no separators, positions matter),
 * like the COBOL copybooks of old banking systems.
 *
 *   pos  len  field
 *   1    36   TXID
 *   37   14   FROM-IBAN
 *   51   14   TO-IBAN
 *   65   15   AMOUNT        (cents, zero-padded, no decimal point: 000000000010000 = 100.00)
 *   80    3   CURRENCY
 *   83   15   CONVERTED     (cents, zero-padded)
 *   98    3   CONV-CURRENCY
 *   101  20   TIMESTAMP     (ISO-8601 UTC)
 *   121   1   STATUS        (A = accepted)
 *   total 121 characters + newline
 */
public class Ledger {

    record Record(String txId, String fromIban, String toIban, BigDecimal amount, String currency,
                  BigDecimal convertedAmount, String convertedCurrency, String timestamp) {}

    static final int RECORD_LENGTH = 121;

    private final Path path;
    private final Set<String> known = new HashSet<>();

    public Ledger(String file) throws IOException {
        this.path = Path.of(file);
        Files.createDirectories(path.getParent());
        if (Files.exists(path)) {
            for (Record r : readAll()) {
                known.add(r.txId());
            }
        }
    }

    public synchronized int count() {
        return known.size();
    }

    /** Appends the order; returns false if it was already there (idempotent). */
    public synchronized boolean append(SettlementOrder o) throws IOException {
        if (known.contains(o.txId())) {
            return false;
        }
        String line = pad(o.txId(), 36) + pad(o.fromIban(), 14) + pad(o.toIban(), 14)
                + cents(o.amount()) + pad(o.currency(), 3)
                + cents(o.convertedAmount()) + pad(o.convertedCurrency(), 3)
                + pad(o.timestamp(), 20) + "A";
        if (line.length() != RECORD_LENGTH) {
            throw new IllegalStateException("registo com tamanho errado: " + line.length());
        }
        Files.writeString(path, line + "\n", StandardCharsets.US_ASCII,
                StandardOpenOption.CREATE, StandardOpenOption.APPEND, StandardOpenOption.SYNC);
        known.add(o.txId());
        return true;
    }

    public synchronized List<Record> readAll() throws IOException {
        List<Record> out = new ArrayList<>();
        if (!Files.exists(path)) {
            return out;
        }
        for (String l : Files.readAllLines(path, StandardCharsets.US_ASCII)) {
            if (l.length() != RECORD_LENGTH) {
                continue;
            }
            out.add(new Record(
                    l.substring(0, 36).trim(), l.substring(36, 50).trim(), l.substring(50, 64).trim(),
                    new BigDecimal(l.substring(64, 79)).movePointLeft(2), l.substring(79, 82),
                    new BigDecimal(l.substring(82, 97)).movePointLeft(2), l.substring(97, 100),
                    l.substring(100, 120).trim()));
        }
        return out;
    }

    static String pad(String value, int width) {
        String v = value.length() > width ? value.substring(0, width) : value;
        return v + " ".repeat(width - v.length());
    }

    static String cents(BigDecimal amount) {
        return String.format("%015d", amount.movePointRight(2).longValueExact());
    }
}
