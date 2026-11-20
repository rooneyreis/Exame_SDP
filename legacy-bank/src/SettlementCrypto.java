import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.util.Base64;
import java.util.HexFormat;

/** Ed25519 + SHA-256 with the standard java.security API (no external libraries). */
public class SettlementCrypto {

    private final PrivateKey ownKey;          // signs the acknowledgements
    private final PublicKey coordinatorKey;   // verifies the orders

    public SettlementCrypto(String privatePemPath, String coordinatorPublicPemPath) throws Exception {
        KeyFactory kf = KeyFactory.getInstance("Ed25519");
        // openssl writes PKCS#8 ("BEGIN PRIVATE KEY") and SubjectPublicKeyInfo ("BEGIN PUBLIC KEY")
        this.ownKey = kf.generatePrivate(new PKCS8EncodedKeySpec(pemBody(privatePemPath)));
        this.coordinatorKey = kf.generatePublic(new X509EncodedKeySpec(pemBody(coordinatorPublicPemPath)));
    }

    static byte[] pemBody(String path) throws Exception {
        String pem = Files.readString(Path.of(path));
        String base64 = pem.replaceAll("-----(BEGIN|END) [A-Z ]+-----", "").replaceAll("\\s", "");
        return Base64.getDecoder().decode(base64);
    }

    public static String sha256Hex(String text) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(md.digest(text.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    public boolean verifyCoordinator(String canonical, String signatureBase64) {
        try {
            Signature verifier = Signature.getInstance("Ed25519");
            verifier.initVerify(coordinatorKey);
            verifier.update(canonical.getBytes(StandardCharsets.UTF_8));
            return verifier.verify(Base64.getDecoder().decode(signatureBase64));
        } catch (Exception e) {     // bad base64, wrong length...
            return false;
        }
    }

    public String sign(String canonical) {
        try {
            Signature signer = Signature.getInstance("Ed25519");
            signer.initSign(ownKey);
            signer.update(canonical.getBytes(StandardCharsets.UTF_8));
            return Base64.getEncoder().encodeToString(signer.sign());
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
