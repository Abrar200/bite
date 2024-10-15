import stripe
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .models import Order, Restaurant

@csrf_exempt
@require_POST
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META['HTTP_STRIPE_SIGNATURE']
    event = None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        # Invalid payload
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return HttpResponse(status=400)

    # Handle the checkout.session.completed event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        
        # Retrieve the order
        order = Order.objects.get(stripe_payment_intent_id=session.payment_intent)
        
        # Update order status
        order.status = 'PAID'
        order.save()

        # Transfer funds to the restaurant's Stripe account
        transfer_amount = int(order.total_price * 100 * 0.8)  # 80% of the total, converted to cents
        stripe.Transfer.create(
            amount=transfer_amount,
            currency="aud",
            destination=order.restaurant.stripe_account_id,
            transfer_group=f"Order-{order.id}",
        )

    return HttpResponse(status=200)