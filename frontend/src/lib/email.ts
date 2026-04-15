import nodemailer from "nodemailer";
import { getBaseUrl } from "./env";

const transporter = nodemailer.createTransport({
  host: process.env.SMTP_HOST,
  port: parseInt(process.env.SMTP_PORT || "587"),
  secure: false,
  auth: {
    user: process.env.SMTP_USER,
    pass: process.env.SMTP_PASSWORD,
  },
});

export async function sendMagicLink(email: string, token: string, instance: string) {
  const baseUrl = getBaseUrl();
  const magicLink = `${baseUrl}/api/auth/verify?token=${token}`;

  const html = `<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Login – ${instance}</title>
</head>
<body style="margin:0;padding:0;background-color:#fafaf9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" role="presentation"
    style="background-color:#fafaf9;min-height:100vh;">
    <tr>
      <td align="center" style="padding:48px 16px 64px;">
        <table width="480" cellpadding="0" cellspacing="0" border="0" role="presentation"
          style="max-width:480px;width:100%;">

          <!-- Brand -->
          <tr>
            <td align="center" style="padding-bottom:32px;">
              <table cellpadding="0" cellspacing="0" border="0" role="presentation">
                <tr>
                  <td align="center"
                    style="width:40px;height:40px;border-radius:10px;background-color:#ebe9e6;border:1px solid #e3e0db;text-align:center;vertical-align:middle;">
                    <span style="font-size:18px;line-height:1;font-weight:600;color:#57534e;font-family:monospace;">&gt;_</span>
                  </td>
                </tr>
              </table>
              <div style="margin-top:12px;font-size:18px;font-weight:600;color:#1c1917;letter-spacing:-0.01em;">
                ${instance}
              </div>
              <div style="margin-top:3px;font-size:12px;color:#a8a29e;font-family:monospace;">
                ${instance}
              </div>
            </td>
          </tr>

          <!-- Card -->
          <tr>
            <td style="background-color:#ffffff;border-radius:12px;border:1px solid #e3e0db;padding:40px 40px 36px;">

              <h1 style="margin:0 0 8px;font-size:18px;font-weight:600;color:#1c1917;letter-spacing:-0.015em;line-height:1.3;">
                Dein Login-Link
              </h1>
              <p style="margin:0 0 28px;font-size:14px;color:#78716c;line-height:1.6;">
                Klick den Button um dich bei ${instance} anzumelden.
                Der Link ist <strong style="color:#44403c;">15 Minuten</strong> gültig.
              </p>

              <!-- CTA Button -->
              <table cellpadding="0" cellspacing="0" border="0" role="presentation">
                <tr>
                  <td style="border-radius:8px;background-color:#1c1917;">
                    <a href="${magicLink}"
                      style="display:inline-block;padding:12px 24px;font-size:14px;font-weight:500;color:#fafaf9;text-decoration:none;border-radius:8px;letter-spacing:-0.01em;">
                      Jetzt einloggen &rarr;
                    </a>
                  </td>
                </tr>
              </table>

              <!-- Divider -->
              <table cellpadding="0" cellspacing="0" border="0" role="presentation" width="100%"
                style="margin:32px 0 28px;">
                <tr>
                  <td style="border-top:1px solid #e3e0db;height:1px;"></td>
                </tr>
              </table>

              <!-- Fallback link -->
              <p style="margin:0 0 6px;font-size:12px;color:#a8a29e;">
                Falls der Button nicht funktioniert, kopiere diesen Link in deinen Browser:
              </p>
              <p style="margin:0;font-size:11px;color:#a8a29e;word-break:break-all;font-family:monospace;line-height:1.5;">
                ${magicLink}
              </p>

            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:24px 8px 0;text-align:center;">
              <p style="margin:0;font-size:12px;color:#a8a29e;line-height:1.6;">
                Falls du diesen Login nicht angefordert hast, kannst du diese E-Mail ignorieren.<br />
                Dein Konto bleibt sicher – der Link funktioniert nur einmal.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>`;

  await transporter.sendMail({
    from: `${instance} <${process.env.SMTP_USER}>`,
    to: email,
    subject: `Dein Login-Link für ${instance}`,
    html,
    text: `Dein Login-Link für ${instance}\n\nKlick diesen Link um dich anzumelden (15 Minuten gültig):\n\n${magicLink}\n\nFalls du diesen Login nicht angefordert hast, ignoriere diese E-Mail.`,
  });
}
