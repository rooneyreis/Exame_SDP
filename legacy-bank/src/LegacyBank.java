import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpsConfigurator;
import com.sun.net.httpserver.HttpsServer;

import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.math.BigDecimal;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.concurrent.Executors;

/**
 * "Mainframe" of the partner bank. Plain JDK, no frameworks:
 *   - com.sun.net.httpserver.HttpsServer (TLS with a PKCS12 keystore from the local CA)
 *   - javax.xml DOM parser (hardened against XXE)
 *   - java.security Ed25519 signatures
 *
 * POST /settlement  receives a signed <SettlementOrder>, answers a signed <SettlementAck>
 * GET  /settlements lists the accepted orders (read from the fixed-width ledger)
 * GET  /health
 */
public class LegacyBank {

    static final int MAX_BODY_BYTES = 64 * 1024;

    private final SettlementCrypto crypto;
    private final Ledger ledger;
    private final BigDecimal maxSettlement;

    LegacyBank(SettlementCrypto crypto, Ledger ledger, BigDecimal maxSettlement) {
        this.crypto = crypto;
        this.ledger = ledger;
        this.maxSettlement = maxSettlement;
    }

    public static void main(String[] args) throws Exception {
        String keystore = env("KEYSTORE", "/certs/legacy-bank.p12");
        char[] password = env("KEYSTORE_PASSWORD", "changeit").toCharArray();
        int port = Integer.parseInt(env("PORT", "9443"));

        SettlementCrypto crypto = new SettlementCrypto(
                env("PRIVATE_KEY", "/keys/private/legacy-bank-ed25519.pem"),
                env("COORDINATOR_PUBLIC_KEY", "/keys/public/coordinator-ed25519.pub.pem"));
        Ledger ledger = new Ledger(env("LEDGER", "/data/ledger.dat"));
        BigDecimal max = new BigDecimal(env("MAX_SETTLEMENT", "20000"));
        LegacyBank bank = new LegacyBank(crypto, ledger, max);

        HttpsServer server = HttpsServer.create(new InetSocketAddress(port), 0);
        server.setHttpsConfigurator(new HttpsConfigurator(sslContext(keystore, password)));
        server.createContext("/settlement", bank::handleSettlement);
        server.createContext("/settlements", bank::handleList);
        server.createContext("/health", ex -> send(ex, 200, "text/plain", "ok"));
        // Java 21 virtual threads: one cheap thread per request (blocking code, scalable).
        server.setExecutor(Executors.newVirtualThreadPerTaskExecutor());
        server.start();
        log("Banco Parceiro (legado) a ouvir em HTTPS :" + port + " | MAX_SETTLEMENT=" + max
                + " | ordens no ledger=" + ledger.count());
    }

    static SSLContext sslContext(String keystorePath, char[] password) throws Exception {
        KeyStore ks = KeyStore.getInstance("PKCS12");
        try (InputStream in = new FileInputStream(keystorePath)) {
            ks.load(in, password);
        }
        KeyManagerFactory kmf = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
        kmf.init(ks, password);
        SSLContext ctx = SSLContext.getInstance("TLS");
        ctx.init(kmf.getKeyManagers(), null, null);
        return ctx;
    }

    // ---------------------------------------------------------------- POST /settlement

    void handleSettlement(HttpExchange ex) throws IOException {
        if (!"POST".equals(ex.getRequestMethod())) {
            send(ex, 405, "text/plain", "método não permitido");
            return;
        }
        byte[] body = ex.getRequestBody().readNBytes(MAX_BODY_BYTES + 1);
        if (body.length > MAX_BODY_BYTES) {
            reply(ex, 413, Ack.rejected("?", "mensagem demasiado grande"));
            return;
        }

        SettlementOrder order;
        try {
            order = Xml.parseOrder(body);
        } catch (Exception e) {
            log("XML inválido rejeitado: " + e.getMessage());
            reply(ex, 400, Ack.rejected("?", "XML inválido: " + e.getMessage()));
            return;
        }

        // 1) integrity: SHA-256 of the canonical content
        String expectedSha = SettlementCrypto.sha256Hex(order.canonical());
        if (!expectedSha.equals(order.sha256())) {
            log("ADULTERACAO_DETETADA tx=" + order.txId() + ": SHA-256 não corresponde");
            reply(ex, 400, Ack.rejected(order.txId(), "SHA-256 não corresponde ao conteúdo (adulteração)"));
            return;
        }
        // 2) origin: Ed25519 signature of the coordinator
        if (!crypto.verifyCoordinator(order.canonical(), order.signature())) {
            log("ADULTERACAO_DETETADA tx=" + order.txId() + ": assinatura Ed25519 inválida");
            reply(ex, 400, Ack.rejected(order.txId(), "assinatura Ed25519 do coordenador inválida"));
            return;
        }
        // 3) business rule of the partner bank
        if (order.convertedAmount().compareTo(maxSettlement) > 0) {
            log("ordem " + order.txId() + " REJEITADA: " + order.convertedAmount() + " > " + maxSettlement);
            reply(ex, 200, Ack.rejected(order.txId(), "valor acima do limite de liquidação (" + maxSettlement + ")"));
            return;
        }
        boolean isNew = ledger.append(order);
        log("ordem " + order.txId() + " ACEITE " + order.amount() + " " + order.currency() + " -> "
                + order.convertedAmount() + " " + order.convertedCurrency() + (isNew ? "" : " (repetida)"));
        reply(ex, 200, Ack.accepted(order.txId(), isNew ? "registada no ledger" : "já registada (idempotente)"));
    }

    void reply(HttpExchange ex, int code, Ack ack) throws IOException {
        send(ex, code, "application/xml; charset=utf-8", Xml.ackToXml(ack, crypto));
    }

    // ---------------------------------------------------------------- GET /settlements

    void handleList(HttpExchange ex) throws IOException {
        send(ex, 200, "application/xml; charset=utf-8", Xml.settlementsToXml(ledger.readAll()));
    }

    // ---------------------------------------------------------------- helpers

    static void send(HttpExchange ex, int code, String type, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", type);
        ex.sendResponseHeaders(code, bytes.length);
        try (OutputStream out = ex.getResponseBody()) {
            out.write(bytes);
        }
    }

    static String env(String name, String fallback) {
        String v = System.getenv(name);
        return v == null || v.isBlank() ? fallback : v;
    }

    static String now() {
        return Instant.now().truncatedTo(ChronoUnit.SECONDS).toString();
    }

    static void log(String msg) {
        System.out.println(now() + " [legacy-bank] " + msg);
    }

    /** Acknowledgement returned to the coordinator. */
    record Ack(String txId, String status, String reason, String timestamp) {
        static Ack accepted(String txId, String reason) { return new Ack(txId, "ACEITE", reason, now()); }
        static Ack rejected(String txId, String reason) { return new Ack(txId, "REJEITADA", reason, now()); }

        /** Exactly what is hashed and signed (the Python side builds the same string). */
        String canonical() {
            return String.join("|", "SettlementAck", "1.0", txId, status, reason, timestamp);
        }
    }
}
