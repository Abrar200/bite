from django.contrib.auth.forms import PasswordResetForm
from django.template import loader
from django.core.mail import EmailMultiAlternatives

class CustomPasswordResetForm(PasswordResetForm):
    def send_mail(self, subject_template_name, email_template_name,
                  context, from_email, to_email, html_email_template_name=None,
                  extra_email_context=None):
        """
        Send a django.core.mail.EmailMultiAlternatives to `to_email`.
        """
        if extra_email_context is not None:
            context.update(extra_email_context)

        subject = loader.render_to_string(subject_template_name, context)
        # Email subject *must not* contain newlines
        subject = ''.join(subject.splitlines())
        body = loader.render_to_string(email_template_name, context)

        email_message = EmailMultiAlternatives(subject, body, from_email, [to_email])
        if html_email_template_name is not None:
            html_email = loader.render_to_string(html_email_template_name, context)
            email_message.attach_alternative(html_email, 'text/html')

        email_message.send()