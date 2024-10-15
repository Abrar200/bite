from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages
from django.contrib.auth.models import User
from django.views import View
from django.contrib.sites.shortcuts import get_current_site
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.conf import settings
from .models import Restaurant, RestaurantUser, Subscription, Menu, MenuItem, ModifierGroup, Modifier, CartItem, CartItemModifier, Order, OrderItem, OrderItemModifier, OrderNotification, LoyaltyProgram, DigitalLoyaltyCard, UserLoyaltyPoints, UserDigitalCard, WeeklySales
import stripe
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags
from django.db import IntegrityError
from django.contrib.auth.views import PasswordResetView, PasswordResetConfirmView
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import ValidationError
from django.template import loader
from .forms import CustomPasswordResetForm
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json
import requests
from jwt import encode
from datetime import datetime, timedelta
from .doordash_integration import create_doordash_order
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .tasks import create_delivery_task, send_pickup_notification_task
from django.utils import timezone
from .sms_sender import send_order_ready_notification

stripe.api_key = settings.STRIPE_SECRET_KEY


def restaurant_landing_page_view(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    menus = Menu.objects.filter(restaurant=restaurant)
    menu_items = MenuItem.objects.filter(menu__restaurant=restaurant)
    context = {
        'restaurant': restaurant,
        'menus': menus,
        'menu_items': menu_items,
        'is_owner': request.user.is_authenticated and (request.user.restaurant == restaurant or request.user.is_superuser)
    }
    return render(request, 'restaurants/restaurant_landing_page.html', context)


def restaurant_registration_view(request):
    if request.method == "POST":
        restaurant_name = request.POST['name']
        email = request.POST['email']
        password1 = request.POST['password1']
        password2 = request.POST['password2']
        description = request.POST.get('description', '')
        landing_page_tagline = request.POST.get('landing_page_tagline', '')
        address = request.POST.get('address', '')
        phone = request.POST.get('phone', '')
        primary_color = request.POST.get('primary_color', '')
        footer_text = request.POST.get('footer_text', '')
        facebook_link = request.POST.get('facebook_link', '')
        instagram_link = request.POST.get('instagram_link', '')
        youtube_link = request.POST.get('youtube_link', '')
        twitter_link = request.POST.get('twitter_link', '')

        landing_page_image = request.FILES.get('landing_page_image')
        logo_image = request.FILES.get('logo_image')
        favicon = request.FILES.get('favicon')
        about_us_image1 = request.FILES.get('about_us_image1')
        about_us_image2 = request.FILES.get('about_us_image2')
        about_us_image3 = request.FILES.get('about_us_image3')
        contact_us_image = request.FILES.get('contact_us_image')

        if password1 != password2:
            messages.error(request, "Passwords do not match.")
            return render(request, 'restaurants/restaurant_registration.html')

        if RestaurantUser.objects.filter(email=email).exists():
            messages.error(request, "An account with this email already exists. Please log in.")
            return render(request, 'restaurants/restaurant_registration.html')

        try:
            restaurant = Restaurant(
                name=restaurant_name,
                email=email,
                description=description,
                landing_page_tagline=landing_page_tagline,
                landing_page_image=landing_page_image,
                address=address,
                phone=phone,
                logo_image=logo_image,
                primary_color=primary_color,
                favicon=favicon,
                about_us_image1=about_us_image1,
                about_us_text1=request.POST.get('about_us_text1', ''),
                about_us_image2=about_us_image2,
                about_us_text2=request.POST.get('about_us_text2', ''),
                about_us_image3=about_us_image3,
                about_us_text3=request.POST.get('about_us_text3', ''),
                contact_us_image=contact_us_image,
                map_iframe_src=request.POST.get('map_iframe_src', ''),
                footer_text=footer_text,
                facebook_link=facebook_link,
                instagram_link=instagram_link,
                youtube_link=youtube_link,
                twitter_link=twitter_link,
                stripe_subscription_id=None,
                stripe_account_id=None,
            )

            # Handle opening and closing times
            for day, _ in Restaurant.DAYS_OF_WEEK:
                is_closed = request.POST.get(f'is_{day}_closed') == 'on'
                setattr(restaurant, f'is_{day}_closed', is_closed)
                
                if not is_closed:
                    open_time = request.POST.get(f'{day}_open')
                    close_time = request.POST.get(f'{day}_close')
                    if open_time and close_time:
                        setattr(restaurant, f'{day}_open', open_time)
                        setattr(restaurant, f'{day}_close', close_time)
                    else:
                        raise ValidationError(f"{day.capitalize()} must have both opening and closing times if not marked as closed.")
                else:
                    setattr(restaurant, f'{day}_open', None)
                    setattr(restaurant, f'{day}_close', None)

            restaurant.full_clean()
            restaurant.save()

            user = RestaurantUser(username=email, email=email, restaurant=restaurant)
            user.set_password(password1)
            user.is_active = False
            user.is_restaurant_admin = True
            user.save()

            send_verification_email(request, user, restaurant.slug)

            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[
                    {
                        'price': settings.STRIPE_MONTHLY_SUBSCRIPTION_PRICE_ID,
                        'quantity': 1,
                    },
                ],
                mode='subscription',
                success_url=request.build_absolute_uri(reverse('post_subscription', args=[restaurant.slug])),
                cancel_url=request.build_absolute_uri(reverse('restaurant_registration')),
            )

            restaurant.stripe_subscription_id = checkout_session.subscription
            restaurant.save()

            messages.success(request, "Account has been created successfully. Please complete the subscription payment and verify your email.")
            return redirect(checkout_session.url, code=303)

        except ValidationError as e:
            messages.error(request, f"Validation error: {str(e)}")
            return render(request, 'restaurants/restaurant_registration.html', {'DAYS_OF_WEEK': Restaurant.DAYS_OF_WEEK})
        except Exception as e:
            print(f"Error occurred: {str(e)}")
            messages.error(request, f"An error occurred during registration. Please try again.")
            return render(request, 'restaurants/restaurant_registration.html', {'DAYS_OF_WEEK': Restaurant.DAYS_OF_WEEK})
    
    context = {
        'GOOGLE_MAPS_API_KEY': settings.GOOGLE_MAPS_API_KEY,
        'DAYS_OF_WEEK': Restaurant.DAYS_OF_WEEK,
    }
    return render(request, 'restaurants/restaurant_registration.html', context)


def post_subscription(request, slug):
    restaurant = Restaurant.objects.get(slug=slug)
    
    try:
        account = stripe.Account.create(
            type='express',
            country='AU',
            email=restaurant.email,
            business_type='individual',
        )
        restaurant.stripe_account_id = account.id
        restaurant.save()

        account_link = stripe.AccountLink.create(
            account=account.id,
            refresh_url=request.build_absolute_uri(reverse('restaurant_registration')),
            return_url=request.build_absolute_uri(reverse('restaurant_landing_page', args=[restaurant.slug])),
            type='account_onboarding',
        )

        messages.success(request, "")
        return redirect(account_link.url)

    except stripe.error.StripeError as e:
        messages.error(request, f"An error occurred with Stripe: {str(e)}")
        return redirect('restaurant_landing_page', slug=slug)

    except Exception as e:
        messages.error(request, f"An unexpected error occurred: {str(e)}")
        return redirect('restaurant_landing_page', slug=slug)

def user_registration_view(request, restaurant_slug=None):
    if request.method == "POST":
        first_name = request.POST['first_name']
        last_name = request.POST['last_name']
        email = request.POST['email']
        password1 = request.POST['password1']
        password2 = request.POST['password2']
        phone = request.POST['phone']
        subscribe = request.POST.get('subscribe', 'off') == 'on'

        if password1 != password2:
            messages.error(request, "Passwords do not match.")
            return render(request, 'restaurants/user_registration.html', {'restaurant_slug': restaurant_slug})

        try:
            user = RestaurantUser(
                username=email,
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                is_active=False
            )
            user.set_password(password1)
            user.save()

            if subscribe and restaurant_slug:
                restaurant = get_object_or_404(Restaurant, slug=restaurant_slug)
                subscription = Subscription(
                    restaurant=restaurant,
                    user=user,
                    email=email,
                    phone=phone,
                    subscribed=True
                )
                subscription.save()

            send_verification_email(request, user, restaurant_slug)

            messages.success(request, "Account has been created successfully. Please verify your email.")
            return redirect(f"{reverse('login', args=[restaurant_slug])}?restaurant={restaurant_slug}")

        except IntegrityError as e:
            if 'UNIQUE constraint' in str(e):
                messages.error(request, "An account with this email already exists. Please log in.")
            else:
                messages.error(request, "An error occurred during registration. Please try again.")
            return render(request, 'restaurants/user_registration.html', {'restaurant_slug': restaurant_slug})

    return render(request, 'restaurants/user_registration.html', {'restaurant_slug': restaurant_slug})

def login_view(request, restaurant_slug=None):
    if request.method == "POST":
        email = request.POST['email']
        password = request.POST['password']
        user = authenticate(request, username=email, password=password)
        
        if user is not None:
            login(request, user)
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('restaurant_landing_page', slug=restaurant_slug)
        else:
            messages.error(request, "Invalid email or password")

    return render(request, 'restaurants/login.html', {'restaurant_slug': restaurant_slug})


def logout_view(request):
    # Get the restaurant slug from the current request, if available
    restaurant_slug = request.GET.get('restaurant_slug')
    
    # Perform the logout operation
    logout(request)
    
    # Display a success message
    messages.success(request, "You have been logged out.")
    
    # Redirect to the login page with the slug if available
    if restaurant_slug:
        return redirect('login', restaurant_slug=restaurant_slug)
    else:
        return redirect('login')  # Fallback if no slug is present

def send_verification_email(request, user, restaurant_slug=None):
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    verification_link = request.build_absolute_uri(reverse('email_verification', args=[uid, token]))
    if restaurant_slug:
        verification_link += f"?restaurant={restaurant_slug}"

    restaurant = user.restaurant if hasattr(user, 'restaurant') else None

    context = {
        'user': user,
        'restaurant': restaurant,
        'verification_url': verification_link,
    }

    subject = "Email Verification"
    html_message = render_to_string('restaurants/email_verification.html', context)
    plain_message = strip_tags(html_message)
    from_email = settings.DEFAULT_FROM_EMAIL
    to_email = user.email

    email = EmailMultiAlternatives(subject, plain_message, from_email, [to_email])
    email.attach_alternative(html_message, "text/html")
    email.send()

def email_verification_view(request, uidb64, token):
    restaurant_slug = request.GET.get('restaurant')
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = RestaurantUser.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, RestaurantUser.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        messages.success(request, "Account has been successfully verified. You can now log in.")
        if restaurant_slug:
            return redirect('login', restaurant_slug=restaurant_slug)  # Corrected line
        else:
            messages.warning(request, "No restaurant context found. Redirecting to login.")
            return redirect('login', restaurant_slug=restaurant_slug)  # No slug, so just go to the login page
    else:
        messages.error(request, "Invalid verification link.")
        return redirect('login', restaurant_slug=restaurant_slug)


def stripe_payment_view(request, restaurant_id):
    restaurant = Restaurant.objects.get(id=restaurant_id)
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'aud',
                'product_data': {
                    'name': f'{restaurant.name} Subscription',
                },
                'unit_amount': 20000,  # $200 in cents
            },
            'quantity': 1,
        }],
        mode='subscription',
        success_url=request.build_absolute_uri(reverse('restaurant_landing_page', args=[restaurant.slug])),
        cancel_url=request.build_absolute_uri(reverse('stripe_payment', args=[restaurant.id])),
    )
    return redirect(session.url, code=303)

class CustomPasswordResetView(PasswordResetView):
    template_name = 'restaurants/forgot_password.html'
    email_template_name = 'restaurants/password_reset_email.html'
    form_class = PasswordResetForm

    def get_success_url(self):
        print(f"DEBUG: get_success_url - restaurant_slug: {self.kwargs.get('restaurant_slug')}")
        return reverse_lazy('password_reset_done', kwargs={'restaurant_slug': self.kwargs['restaurant_slug']})

    def form_valid(self, form):
        email = form.cleaned_data['email']
        restaurant_slug = self.kwargs.get('restaurant_slug')
        print(f"DEBUG: form_valid - restaurant_slug: {restaurant_slug}")
        restaurant = get_object_or_404(Restaurant, slug=restaurant_slug)

        # Get the user associated with the provided email
        UserModel = RestaurantUser
        try:
            user = UserModel.objects.get(email=email)
        except UserModel.DoesNotExist:
            form.add_error('email', ValidationError("No user is associated with this email address."))
            return self.form_invalid(form)

        # Prepare the context
        context = {
            'uid': urlsafe_base64_encode(force_bytes(user.pk)),
            'token': default_token_generator.make_token(user),
            'protocol': self.request.scheme,
            'domain': self.request.get_host(),
            'restaurant_slug': restaurant_slug,
            'restaurant': restaurant,
            'primary_color': restaurant.primary_color,
        }
        print(f"DEBUG: form_valid - context: {context}")

        # Render HTML content
        subject = "Password Reset Requested"
        html_content = render_to_string('restaurants/password_reset_email.html', context)
        text_content = strip_tags(html_content)

        print(f"DEBUG: form_valid - Full html_content:\n{html_content}")

        print(f"DEBUG: form_valid - html_content: {html_content[:100]}...")  # Print first 100 chars

        # Send email using EmailMultiAlternatives
        email = EmailMultiAlternatives(subject, text_content, settings.DEFAULT_FROM_EMAIL, [email])
        email.attach_alternative(html_content, "text/html")
        email.send()

        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['restaurant_slug'] = self.kwargs.get('restaurant_slug')
        print(f"DEBUG: get_context_data - restaurant_slug: {context['restaurant_slug']}")
        return context
    

from django.contrib.auth.views import PasswordResetDoneView

class CustomPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'restaurants/password_reset_done.html'

    def get(self, request, *args, **kwargs):
        print(f"DEBUG: CustomPasswordResetDoneView.get - kwargs: {kwargs}")
        return super().get(request, *args, **kwargs)


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'restaurants/reset_password.html'

    def dispatch(self, *args, **kwargs):
        print(f"DEBUG: CustomPasswordResetConfirmView.dispatch - args: {args}")
        print(f"DEBUG: CustomPasswordResetConfirmView.dispatch - kwargs: {kwargs}")
        return super().dispatch(*args, **kwargs)

    def get_success_url(self):
        print(f"DEBUG: CustomPasswordResetConfirmView.get_success_url - kwargs: {self.kwargs}")
        return reverse_lazy('password_reset_complete', kwargs={
            'restaurant_slug': self.kwargs['restaurant_slug'],
        })

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        restaurant_slug = self.kwargs.get('restaurant_slug')
        print(f"DEBUG: CustomPasswordResetConfirmView.get_context_data - restaurant_slug: {restaurant_slug}")
        if not restaurant_slug:
            messages.error(self.request, "Invalid restaurant context. Please try again.")
            return context
        context['restaurant_slug'] = restaurant_slug
        context['restaurant'] = get_object_or_404(Restaurant, slug=restaurant_slug)
        return context
    
from datetime import datetime

def format_time(time_str):
    if not time_str:
        return 'N/A'
    try:
        time_obj = datetime.strptime(time_str, '%H:%M').time()
        return time_obj.strftime('%I:%M %p')
    except ValueError:
        return 'Invalid Time'
    

@login_required
def restaurant_dashboard(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    if request.user.restaurant != restaurant and not request.user.is_superuser:
        messages.error(request, "You don't have permission to access this dashboard.")
        return redirect('restaurant_landing_page', slug=slug)
    
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Handle delivery settings
                restaurant.delivery_fee_contribution = request.POST.get('delivery_fee_contribution') == 'on'
                restaurant.delivery_fee_contribution_percentage = Decimal(request.POST.get('delivery_fee_contribution_percentage', 0))
                free_delivery_threshold = request.POST.get('free_delivery_threshold')
                restaurant.free_delivery_threshold = Decimal(free_delivery_threshold) if free_delivery_threshold else None
                restaurant.is_accepting_orders = 'is_accepting_orders' in request.POST

                # Handle opening and closing times
                for day, _ in Restaurant.DAYS_OF_WEEK:
                    is_closed = request.POST.get(f'is_{day}_closed') == 'on'
                    setattr(restaurant, f'is_{day}_closed', is_closed)
                    
                    if not is_closed:
                        open_time = request.POST.get(f'{day}_open')
                        close_time = request.POST.get(f'{day}_close')
                        if open_time and close_time:
                            setattr(restaurant, f'{day}_open', open_time)
                            setattr(restaurant, f'{day}_close', close_time)
                        else:
                            raise ValidationError(f"{day.capitalize()} must have both opening and closing times if not marked as closed.")
                    else:
                        setattr(restaurant, f'{day}_open', None)
                        setattr(restaurant, f'{day}_close', None)

                restaurant.full_clean()
                restaurant.save()
                messages.success(request, "Restaurant details updated successfully.")
                
                # Refresh the restaurant object to get the updated data
                restaurant.refresh_from_db()
        except ValidationError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
    
    # Fetch the last 4 weeks of sales reports
    today = timezone.now().date()
    four_weeks_ago = today - timezone.timedelta(weeks=4)
    weekly_sales = WeeklySales.objects.filter(
        restaurant=restaurant,
        week_start__gte=four_weeks_ago
    ).order_by('-week_start')

    # Ensure totals are up-to-date
    for sale in weekly_sales:
        sale.update_totals()

    menus = Menu.objects.filter(restaurant=restaurant)
    orders = Order.objects.filter(restaurant=restaurant, status='PAID').order_by('-created_at')
    subscribers = Subscription.objects.filter(restaurant=restaurant, subscribed=True)
    notifications = OrderNotification.objects.filter(order__restaurant=restaurant, is_read=False)
    
    context = {
        'restaurant': restaurant,
        'weekly_sales': weekly_sales,
        'orders': orders,
        'notifications': notifications,
        'subscribers': subscribers,
        'menus': menus,
        'WEBSOCKET_URL': f"ws://{request.get_host()}/ws/orders/{slug}/",
        'DAYS_OF_WEEK': Restaurant.DAYS_OF_WEEK,
        'formatted_hours': restaurant.get_formatted_hours(),
    }
    return render(request, 'restaurants/restaurant_dashboard.html', context)

def notify_order_update(order):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"restaurant_{order.restaurant.slug}",
        {
            'type': 'new_order_notification',
            'order_id': order.id,
        }
    )

def order_detail(request, slug, order_id):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    order = get_object_or_404(Order, id=order_id, restaurant=restaurant)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        with transaction.atomic():
            # Refresh the order to get the latest state
            order.refresh_from_db()
            
            if action == 'update_preparation_time':
                preparation_time = int(request.POST.get('preparation_time'))
                order.preparation_time = preparation_time
                order.preparation_start_time = timezone.now()
                order.status = 'PREPARING'
                order.save()
                
                if preparation_time == 0:
                    order.status = 'READY'
                    order.save()
                
                # Schedule tasks only if they haven't been scheduled before
                if not order.sms_sent:
                    if order.order_type == 'DELIVERY' and not order.doordash_delivery_id:
                        create_delivery_task(order.id, schedule=timezone.now() + timezone.timedelta(minutes=preparation_time))
                    elif order.order_type in ['PICKUP', 'TAKEOUT']:
                        send_pickup_notification_task(order.id, schedule=timezone.now() + timezone.timedelta(minutes=preparation_time))
                
                messages.success(request, f"Order preparation started. Estimated time: {preparation_time} minutes.")
            
            elif action == 'mark_as_ready':
                order.status = 'READY'
                order.save()
                
                # Send notifications only if they haven't been sent before
                if not order.sms_sent:
                    if order.order_type == 'DELIVERY' and not order.doordash_delivery_id:
                        create_delivery_task(order.id)
                    elif order.order_type in ['PICKUP', 'TAKEOUT']:
                        send_pickup_notification_task(order.id)
                
                messages.success(request, "Order marked as ready.")
        
        # Send WebSocket notification about order status update
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"restaurant_{slug}",
            {
                "type": "order_status_update",
                "order_id": order.id,
                "status": order.status,
            },
        )
        
        return redirect('order_detail', slug=slug, order_id=order_id)
    
    context = {
        'restaurant': restaurant,
        'order': order,
    }
    return render(request, 'restaurants/order_detail.html', context)

def order_partial_view(request, slug, order_id):
    order = get_object_or_404(Order, id=order_id, restaurant__slug=slug)
    context = {
        'order': order,
    }
    return render(request, 'restaurants/_order_partial.html', context)

def send_pickup_notification(order):
    phone_number = order.user.phone if order.user else order.guest_phone
    message = f"Your order from {order.restaurant.name} is ready for pickup. Please come and collect it."
    print(f"Sending SMS to {phone_number}: {message}")

@login_required
def add_menu(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    if request.user.restaurant != restaurant and not request.user.is_superuser:
        messages.error(request, "You don't have permission to add menus to this restaurant.")
        return redirect('restaurant_landing_page', slug=slug)

    if request.method == "POST":
        name = request.POST['name']
        description = request.POST.get('description', '')
        image = request.FILES.get('image')

        menu = Menu.objects.create(
            restaurant=restaurant,
            name=name,
            description=description,
            image=image
        )
        messages.success(request, f"Menu '{name}' has been added successfully.")
        return redirect('restaurant_dashboard', slug=slug)

    return render(request, 'restaurants/add_menu.html', {'restaurant': restaurant})


@login_required
def add_menu_item(request, slug, menu_id):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    menu = get_object_or_404(Menu, id=menu_id, restaurant=restaurant)
    if request.user.restaurant != restaurant and not request.user.is_superuser:
        messages.error(request, "You don't have permission to add menu items to this restaurant.")
        return redirect('restaurant_landing_page', slug=slug)

    if request.method == "POST":
        name = request.POST['name']
        description = request.POST.get('description', '')
        try:
            price = Decimal(request.POST['price'])
        except InvalidOperation:
            messages.error(request, "Invalid price format. Please enter a valid number.")
            return render(request, 'restaurants/add_menu_item.html', {'restaurant': restaurant, 'menu': menu})
        
        image1 = request.FILES.get('image1')
        image2 = request.FILES.get('image2')
        image3 = request.FILES.get('image3')

        menu_item = MenuItem(
            menu=menu,
            name=name,
            description=description,
            price=price,
            image1=image1,
            image2=image2,
            image3=image3
        )
        menu_item.save()

        print(f"Menu item {menu_item.name} added to Menu {menu.name}.", file=sys.stderr)
        print(f"Checking if Restaurant has loyalty program setup", file=sys.stderr)

        loyalty_program = LoyaltyProgram.objects.filter(restaurant=restaurant).first()
        if loyalty_program:
            print(f"Found loyalty program for restaurant - {loyalty_program.program_type} program", file=sys.stderr)
            print(f"Menu item points multiplier for program - {loyalty_program.menu_item_points_multiplier}", file=sys.stderr)
            points_price = menu_item.calculate_points_price()
            print(f"So points price for menu item - ${menu_item.price} x {loyalty_program.menu_item_points_multiplier} = {points_price} points", file=sys.stderr)
        else:
            print(f"No loyalty program found for restaurant {restaurant.name}", file=sys.stderr)

        messages.success(request, f"Menu item '{name}' has been added successfully.")
        return redirect('restaurant_dashboard', slug=slug)

    return render(request, 'restaurants/add_menu_item.html', {'restaurant': restaurant, 'menu': menu})


from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.exceptions import ValidationError
from django.db import transaction


@login_required
@require_http_methods(["GET", "POST"])
def add_modifier(request, slug, menu_item_id):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    menu_item = get_object_or_404(MenuItem, id=menu_item_id, menu__restaurant=restaurant)
    if request.user.restaurant != restaurant and not request.user.is_superuser:
        return JsonResponse({
            'success': False,
            'error': "You don't have permission to add modifiers to this menu item."
        }, status=403)

    if request.method == "POST":
        try:
            print(f"Received POST data: {request.POST}")
            
            with transaction.atomic():
                group_name = request.POST['group_name']
                selection_type = request.POST['selection_type']
                
                # Set min and max selections based on selection type
                if selection_type == 'SINGLE':
                    min_selections = 1
                    max_selections = 1
                else:
                    min_selections = int(request.POST.get('min_selections', 0))
                    max_selections = request.POST.get('max_selections')
                    max_selections = int(max_selections) if max_selections else None

                print(f"Creating ModifierGroup: name={group_name}, selection_type={selection_type}, min_selections={min_selections}, max_selections={max_selections}")

                modifier_group = ModifierGroup.objects.create(
                    menu_item=menu_item,
                    name=group_name,
                    selection_type=selection_type,
                    min_selections=min_selections,
                    max_selections=max_selections
                )

                modifier_names = request.POST.getlist('modifier_name[]')
                modifier_prices = request.POST.getlist('modifier_price[]')
                price_varies = request.POST.getlist('price_varies[]')

                print(f"Modifier data: names={modifier_names}, prices={modifier_prices}, price_varies={price_varies}")

                created_modifiers = []
                for name, price, varies in zip(modifier_names, modifier_prices, price_varies):
                    price_varies_bool = varies == 'on'
                    if price_varies_bool:
                        price = price or None  # Use provided price or None if empty
                    else:
                        price = price or 0  # Use provided price or 0 if empty

                    modifier = Modifier.objects.create(
                        group=modifier_group,
                        name=name,
                        price=price,
                        price_varies=price_varies_bool
                    )
                    created_modifiers.append(modifier)
                    print(f"Created modifier: {modifier}")

                print(f"Total modifiers created: {len(created_modifiers)}")

            messages.success(request, f"Modifier group '{group_name}' has been added successfully with {len(created_modifiers)} modifiers.")
            return JsonResponse({
                'success': True,
                'redirect_url': reverse('restaurant_dashboard', kwargs={'slug': slug})
            })
            
        except ValidationError as e:
            print(f"ValidationError: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)
        except Exception as e:
            print(f"Unexpected error: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': f"An unexpected error occurred: {str(e)}"
            }, status=500)

    return render(request, 'restaurants/add_modifier.html', {'restaurant': restaurant, 'menu_item': menu_item})

from django.db import transaction
from django.db.utils import OperationalError
import time

def menu_item_detail(request, restaurant_slug, item_id):
    restaurant = get_object_or_404(Restaurant, slug=restaurant_slug)
    menu_item = get_object_or_404(MenuItem, id=item_id, menu__restaurant=restaurant)
    context = {
        'restaurant': restaurant,
        'menu_item': menu_item,
    }
    return render(request, 'restaurants/menu_item_detail.html', context)

def add_to_cart_view(request, slug, menu_item_id):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    menu_item = get_object_or_404(MenuItem, id=menu_item_id, menu__restaurant=restaurant)

    if request.method == "POST":
        quantity = int(request.POST.get('quantity', 1))
        notes = request.POST.get('notes', '')
        is_reward_item = request.POST.get('is_reward_item') == 'true'

        print(f"Received POST data: {request.POST}")
        for key, value in request.POST.items():
            print(f"{key}: {value}")

        print(f"Checking menuitem has modifiers: {'Yes' if menu_item.modifier_groups.exists() else 'No'}")
        print(f"Checking number of modifiers: {menu_item.modifier_groups.count()}")

        # Validate modifier selection
        selected_modifiers = {}
        for modifier_group in menu_item.modifier_groups.all():
            group_modifiers = request.POST.getlist(f'modifier_group_{modifier_group.id}')
            
            print(f"Modifier Group: {modifier_group.name}")
            print(f"  Min selections: {modifier_group.min_selections}")
            print(f"  Max selections: {modifier_group.max_selections or 'No limit'}")
            print(f"  Selected modifiers: {group_modifiers}")
            print(f"  Number of selections: {len(group_modifiers)}")
            
            if len(group_modifiers) < modifier_group.min_selections:
                return JsonResponse({
                    'success': False,
                    'error': f"Please select at least {modifier_group.min_selections} {modifier_group.name}."
                })
            
            if modifier_group.max_selections and len(group_modifiers) > modifier_group.max_selections:
                return JsonResponse({
                    'success': False,
                    'error': f"You can select up to {modifier_group.max_selections} {modifier_group.name}."
                })

            selected_modifiers[modifier_group.id] = group_modifiers

        max_retries = 5
        retry_delay = 0.1  # seconds

        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    # Check if the item already exists in the cart
                    if request.user.is_authenticated:
                        cart_item = CartItem.objects.filter(
                            menu_item=menu_item,
                            user=request.user,
                            restaurant=restaurant,
                            is_reward_item=is_reward_item
                        ).first()
                    else:
                        guest_phone = request.session.get('guest_phone')
                        if not guest_phone:
                            return JsonResponse({
                                'success': False,
                                'error': "Please provide a phone number for guest checkout.",
                                'redirect_url': reverse('guest_checkout', args=[slug])
                            })
                        cart_item = CartItem.objects.filter(
                            menu_item=menu_item,
                            guest_phone=guest_phone,
                            restaurant=restaurant,
                            is_reward_item=is_reward_item
                        ).first()

                    # If the item exists and has the same modifiers, update quantity
                    if cart_item:
                        existing_modifiers = set(cart_item.selected_modifiers.values_list('modifier_id', flat=True))
                        new_modifiers = set([int(mod_id) for group_mods in selected_modifiers.values() for mod_id in group_mods])
                        
                        if existing_modifiers == new_modifiers:
                            cart_item.quantity += quantity
                            cart_item.notes = notes  # Update notes
                            cart_item.save()
                        else:
                            # If modifiers are different, create a new cart item
                            cart_item = None

                    # If the item doesn't exist or has different modifiers, create a new one
                    if not cart_item:
                        if request.user.is_authenticated:
                            cart_item = CartItem.objects.create(
                                menu_item=menu_item,
                                user=request.user,
                                restaurant=restaurant,
                                quantity=quantity,
                                notes=notes,
                                is_reward_item=is_reward_item
                            )
                        else:
                            cart_item = CartItem.objects.create(
                                menu_item=menu_item,
                                guest_phone=guest_phone,
                                restaurant=restaurant,
                                quantity=quantity,
                                notes=notes,
                                is_reward_item=is_reward_item
                            )

                        # Add modifiers to the new cart item
                        for group_id, modifiers in selected_modifiers.items():
                            for modifier_id in modifiers:
                                modifier = Modifier.objects.get(id=modifier_id)
                                CartItemModifier.objects.create(
                                    cart_item=cart_item,
                                    modifier=modifier
                                )

                messages.success(request, f"{menu_item.name} added to cart successfully.")
                return JsonResponse({
                    'success': True,
                    'redirect_url': reverse('cart_view', args=[restaurant.slug])
                })

            except OperationalError as e:
                if attempt == max_retries - 1:
                    print(f"Failed to add item to cart after {max_retries} attempts: {str(e)}")
                    return JsonResponse({
                        'success': False,
                        'error': "Unable to add item to cart. Please try again."
                    })
                time.sleep(retry_delay)

    return render(request, 'restaurants/menu_item_detail.html', {'menu_item': menu_item, 'restaurant': restaurant})


def guest_checkout_view(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    if request.method == "POST":
        phone = request.POST['phone']
        if phone:
            request.session['guest_phone'] = phone
            messages.success(request, "Phone number saved for guest checkout.")
            return redirect('restaurant_landing_page', slug=slug)
        else:
            messages.error(request, "Please provide a valid phone number.")
    return render(request, 'restaurants/guest_checkout.html', {'restaurant': restaurant})


def check_restaurant_availability(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    now = timezone.localtime(timezone.now())
    current_day = now.strftime('%A').lower()
    current_time = now.time()

    is_open = False
    message = ""

    # Check if the restaurant is open today
    if getattr(restaurant, f'is_{current_day}_closed'):
        message = f"Sorry, {restaurant.name} is not open on {current_day.capitalize()}."
    else:
        opening_time = getattr(restaurant, f'{current_day}_open')
        closing_time = getattr(restaurant, f'{current_day}_close')
        
        if opening_time <= current_time <= closing_time:
            is_open = True
            message = f"{restaurant.name} is open."
        else:
            message = f"Sorry, {restaurant.name} is not open at {now.strftime('%I:%M %p')} on {current_day.capitalize()}."

    # Check if the restaurant is accepting orders
    if is_open and not restaurant.is_accepting_orders:
        is_open = False
        message = f"Sorry, {restaurant.name} is not accepting orders at the moment."

    return JsonResponse({
        'is_available': is_open,
        'message': message
    })


def cart_view(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)

    if request.user.is_authenticated:
        cart_items = CartItem.objects.filter(user=request.user, restaurant=restaurant)
    else:
        guest_phone = request.session.get('guest_phone')
        if not guest_phone:
            return redirect('guest_checkout', slug=slug)
        cart_items = CartItem.objects.filter(guest_phone=guest_phone, restaurant=restaurant)

    total_price = sum(item.total_price for item in cart_items if not item.is_reward_item)

    context = {
        'cart_items': cart_items,
        'total_price': total_price,
        'restaurant': restaurant,
        'STRIPE_PUBLISHABLE_KEY': settings.STRIPE_PUBLISHABLE_KEY,
        'GOOGLE_MAPS_API_KEY': settings.GOOGLE_MAPS_API_KEY,
    }

    return render(request, 'restaurants/cart.html', context)


@csrf_exempt
@require_POST
def create_checkout_session(request, slug):
    try:
        restaurant = get_object_or_404(Restaurant, slug=slug)
        data = json.loads(request.body)
        order_type = data.get('orderType')
        delivery_location = data.get('deliveryLocation')
        delivery_fee = Decimal(data.get('deliveryFee', '0'))

        if request.user.is_authenticated:
            cart_items = CartItem.objects.filter(user=request.user, restaurant=restaurant)
        else:
            guest_phone = request.session.get('guest_phone')
            if not guest_phone:
                return JsonResponse({'error': 'Guest checkout requires a phone number'}, status=400)
            cart_items = CartItem.objects.filter(guest_phone=guest_phone, restaurant=restaurant)

        if not cart_items:
            return JsonResponse({'error': 'Your cart is empty'}, status=400)

        # Calculate the subtotal from cart items
        subtotal = sum(item.total_price for item in cart_items if not item.is_reward_item)

        # Apply delivery fee logic
        if order_type == 'DELIVERY':
            if restaurant.free_delivery_threshold and subtotal >= restaurant.free_delivery_threshold:
                customer_delivery_fee = Decimal('0.00')
                store_contribution = delivery_fee
            elif restaurant.delivery_fee_contribution:
                store_contribution = (delivery_fee * restaurant.delivery_fee_contribution_percentage / 100).quantize(Decimal('0.01'))
                customer_delivery_fee = delivery_fee - store_contribution
            else:
                customer_delivery_fee = delivery_fee
                store_contribution = Decimal('0.00')
        else:
            customer_delivery_fee = Decimal('0.00')
            store_contribution = Decimal('0.00')

        total_price = subtotal + customer_delivery_fee
        
        # Create a single line item for the entire order
        line_items = [{
            'price_data': {
                'currency': 'aud',
                'unit_amount': int(total_price * 100),  # Convert to cents
                'product_data': {
                    'name': f'Order from {restaurant.name}',
                },
            },
            'quantity': 1,
        }]

        with transaction.atomic():
            # Get or create the current week's WeeklySales object
            weekly_sales, created = WeeklySales.get_or_create_current_week(restaurant)

            # Create the order instance
            order = Order.objects.create(
                restaurant=restaurant,
                user=request.user if request.user.is_authenticated else None,
                guest_phone=guest_phone if not request.user.is_authenticated else None,
                order_type=order_type,
                delivery_location=delivery_location,
                status='PENDING',
                total_price=subtotal,
                delivery_fee=delivery_fee,
                customer_delivery_fee=customer_delivery_fee,
                store_contribution=store_contribution,
                weekly_sales=weekly_sales
            )

            weekly_sales.update_totals()

            # Create OrderItem instances
            for cart_item in cart_items:
                order_item = OrderItem.objects.create(
                    order=order,
                    menu_item=cart_item.menu_item,
                    quantity=cart_item.quantity,
                    price=Decimal('0.00') if cart_item.is_reward_item else cart_item.menu_item.price,
                    notes=cart_item.notes,
                    is_reward_item=cart_item.is_reward_item
                )
                
                for cart_modifier in cart_item.selected_modifiers.all():
                    OrderItemModifier.objects.create(
                        order_item=order_item,
                        modifier=cart_modifier.modifier,
                        price=Decimal('0.00') if cart_item.is_reward_item else cart_modifier.modifier.price
                    )

            # Update weekly sales
            weekly_sales.total_sales += subtotal
            weekly_sales.total_delivery_fees += delivery_fee
            weekly_sales.total_store_contributions += store_contribution
            weekly_sales.total_customer_delivery_fees += customer_delivery_fee
            weekly_sales.save()

        if total_price > Decimal('0.00'):
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=line_items,
                mode='payment',
                success_url=request.build_absolute_uri(reverse('payment_success', args=[restaurant.slug])) + f'?session_id={{CHECKOUT_SESSION_ID}}',
                cancel_url=request.build_absolute_uri(reverse('payment_cancel', args=[restaurant.slug])),
                client_reference_id=str(order.id),
                metadata={'order_id': order.id, 'delivery_location': delivery_location}
            )

            order.stripe_payment_intent_id = checkout_session.payment_intent
            order.save()

            return JsonResponse({'sessionId': checkout_session.id})
        else:
            # Handle free orders (e.g., reward items)
            order.status = 'PAID'
            order.save()
            
            # Process loyalty program
            update_digital_loyalty_cards(order)
            loyalty_points = calculate_loyalty_points(order)
            order.loyalty_points_earned = loyalty_points
            order.save()

            if request.user.is_authenticated:
                user_points, created = UserLoyaltyPoints.objects.get_or_create(
                    user=request.user,
                    restaurant=order.restaurant
                )
                user_points.points += loyalty_points
                user_points.save()

            clear_cart(request)

            # Notify restaurant about the new order
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"orders_{restaurant.slug}",
                {
                    "type": "order_notification",
                    "message": {
                        "status": "new_order",
                        "order_id": order.id
                    }
                }
            )

            return JsonResponse({'redirect': reverse('order_confirmation', args=[order.id])})

    except stripe.error.StripeError as e:
        print(f"Stripe error: {str(e)}", file=sys.stderr)
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        print(f"Unexpected error: {str(e)}", file=sys.stderr)
        return JsonResponse({'error': str(e)}, status=400)

from decimal import Decimal, InvalidOperation

def payment_success(request, slug):
    print("Post data now:", request.GET)  # Debug: Print GET data
    
    session_id = request.GET.get('session_id')
    
    if not session_id:
        messages.error(request, "No session ID provided.")
        return redirect('cart_view', slug=slug)

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        payment_intent = stripe.PaymentIntent.retrieve(session.payment_intent)

        if payment_intent.status != 'succeeded':
            messages.error(request, "Payment was not successful.")
            return redirect('cart_view', slug=slug)

        order_id = session.metadata.get('order_id')
        order = get_object_or_404(Order, id=order_id)

        print("Quantity after going to Stripe:")  # Debug: Print quantities
        for item in order.items.all():
            print(f"{item.menu_item.name}: {item.quantity}")

        with transaction.atomic():
            order.status = 'PAID'
            order.stripe_payment_intent_id = session.payment_intent

            # Update weekly sales
            weekly_sales = order.weekly_sales
            weekly_sales.total_sales += order.total_price
            weekly_sales.save()

            # Check and update the digital loyalty cards after payment success
            print(f"Checking for digital loyalty card program for order {order.id}", file=sys.stderr)
            update_digital_loyalty_cards(order)

            # Calculate and add loyalty points
            loyalty_points = calculate_loyalty_points(order)
            order.loyalty_points_earned = loyalty_points
            order.save()

            if request.user.is_authenticated:
                user_points, created = UserLoyaltyPoints.objects.get_or_create(
                    user=request.user,
                    restaurant=order.restaurant
                )
                user_points.points += loyalty_points
                user_points.save()

        clear_cart(request)

        # Notify restaurant about the new order
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"orders_{order.restaurant.slug}",
            {
                "type": "order_notification",
                "message": {
                    "status": "new_order",
                    "order_id": order.id
                }
            }
        )

        messages.success(request, "Your order has been placed and paid for successfully!")
        return redirect('order_confirmation', order_id=order.id)

    except stripe.error.StripeError as e:
        print(f"Stripe error: {str(e)}", file=sys.stderr)
        messages.error(request, f"An error occurred with the payment: {str(e)}")
        return redirect('cart_view', slug=slug)
    except Exception as e:
        print(f"Unexpected error during payment success: {str(e)}", file=sys.stderr)
        messages.error(request, f"An unexpected error occurred: {str(e)}")
        return redirect('cart_view', slug=slug)

def update_digital_loyalty_cards(order):
    if not order.user:
        print("Skipping digital loyalty card update for guest order", file=sys.stderr)
        return  # Skip for guest orders

    print(f"Checking for digital loyalty card program for order {order.id}", file=sys.stderr)
    
    for item in order.items.all():
        if not item.is_reward_item:  # Only count non-reward items
            digital_card = DigitalLoyaltyCard.objects.filter(
                restaurant=order.restaurant,
                menu_item=item.menu_item
            ).first()
            
            if digital_card:
                print(f"Digital Loyalty Card Program found for {item.menu_item.name}", file=sys.stderr)
                print(f"Buy Quantity: {digital_card.buy_quantity}", file=sys.stderr)
                print(f"Free Quantity: {digital_card.free_quantity}", file=sys.stderr)
                print(f"Order Quantity: {item.quantity}", file=sys.stderr)

                user_card, created = UserDigitalCard.objects.get_or_create(
                    user=order.user,
                    digital_card=digital_card
                )

                user_card.current_count += item.quantity
                print(f"New count after order: {user_card.current_count}", file=sys.stderr)

                while user_card.current_count >= digital_card.buy_quantity:
                    earned_rewards = 1  # Always earn 1 reward at a time
                    user_card.unredeemed_rewards += earned_rewards * digital_card.free_quantity
                    user_card.current_count -= digital_card.buy_quantity
                    
                    print(f"Fulfilled the counter {user_card.current_count}/{digital_card.buy_quantity}", file=sys.stderr)
                    print(f"Customer earns {earned_rewards * digital_card.free_quantity} free {item.menu_item.name}(s)", file=sys.stderr)
                    print(f"Unredeemed rewards: {user_card.unredeemed_rewards}", file=sys.stderr)
                    print(f"Remaining count: {user_card.current_count}", file=sys.stderr)

                user_card.save()
            else:
                print(f"No Digital Loyalty Card Program found for {item.menu_item.name}", file=sys.stderr)

def calculate_loyalty_points(order):
    restaurant = order.restaurant
    loyalty_program = LoyaltyProgram.objects.filter(restaurant=restaurant).first()
    if not loyalty_program:
        print(f"No loyalty program found for {restaurant.name}", file=sys.stderr)
        return Decimal('0.00')
    
    print(f"Calculating loyalty points for order {order.id}", file=sys.stderr)
    print(f"Order total: ${order.total_price}", file=sys.stderr)
    print(f"Loyalty Program Type: {loyalty_program.program_type}", file=sys.stderr)
    
    paid_total = sum(item.price * item.quantity for item in order.items.all() if not item.is_reward_item)
    points_earned = loyalty_program.calculate_points_earned(paid_total)
    
    print(f"Points earned: {points_earned}", file=sys.stderr)
    return points_earned

def clear_cart(request):
    if request.user.is_authenticated:
        CartItem.objects.filter(user=request.user).delete()
    else:
        guest_phone = request.session.get('guest_phone')
        if guest_phone:
            CartItem.objects.filter(guest_phone=guest_phone).delete()
    if 'guest_phone' in request.session:
        del request.session['guest_phone']

def order_confirmation(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    
    # Check if the user is authenticated
    if request.user.is_authenticated:
        # For authenticated users, check if they have permission to view this order
        if order.user != request.user and not request.user.is_superuser:
            messages.error(request, "You don't have permission to view this order.")
            return redirect('restaurant_landing_page', slug=order.restaurant.slug)
    else:
        # For guest users, check if their phone number matches the order's guest_phone
        # or if the order ID matches the one stored in the session
        guest_phone = request.session.get('guest_phone')
        last_order_id = request.session.get('last_order_id')
        if (not guest_phone or order.guest_phone != guest_phone) and order.id != last_order_id:
            messages.error(request, "You don't have permission to view this order.")
            return redirect('restaurant_landing_page', slug=order.restaurant.slug)
    
    context = {
        'order': order,
        'restaurant': order.restaurant,
    }
    return render(request, 'restaurants/order_confirmation.html', context)

def clear_cart(request):
    if request.user.is_authenticated:
        CartItem.objects.filter(user=request.user).delete()
    else:
        guest_phone = request.session.get('guest_phone')
        if guest_phone:
            CartItem.objects.filter(guest_phone=guest_phone).delete()
    if 'guest_phone' in request.session:
        del request.session['guest_phone']

def payment_cancel(request, slug):
    messages.warning(request, "Your payment was cancelled.")
    return redirect('cart_view', slug=slug)


from .consumers import send_order_notification

def create_order_from_session(session):
    restaurant = Restaurant.objects.get(id=session.metadata['restaurant_id'])
    
    order = Order.objects.create(
        restaurant=restaurant,
        user_id=session.metadata.get('user_id'),
        guest_phone=session.metadata.get('guest_phone'),
        order_type=session.metadata['order_type'],
        status='PAID',
        total_price=session.amount_total / 100,  # Convert from cents to dollars
        stripe_payment_intent_id=session.payment_intent
    )

    send_order_notification(order)

    if session.metadata.get('user_id'):
        cart_items = CartItem.objects.filter(user_id=session.metadata['user_id'], restaurant=restaurant)
    else:
        cart_items = CartItem.objects.filter(guest_phone=session.metadata['guest_phone'], restaurant=restaurant)

    for cart_item in cart_items:
        order_item = OrderItem.objects.create(
            order=order,
            menu_item=cart_item.menu_item,
            quantity=cart_item.quantity,
            price=cart_item.menu_item.price,
            notes=cart_item.notes
        )
        
        for cart_modifier in cart_item.selected_modifiers.all():
            OrderItemModifier.objects.create(
                order_item=order_item,
                modifier=cart_modifier.modifier,
                price=cart_modifier.modifier.price
            )

    return order


@require_POST
def accept_order(request, slug, order_id):
    order = get_object_or_404(Order, id=order_id, restaurant__slug=slug)
    preparation_time = int(request.POST.get('preparation_time', 0))

    order.status = 'PREPARING'
    order.preparation_time = preparation_time
    order.preparation_start_time = timezone.now()
    order.save()

    if order.order_type == 'DELIVERY':
        create_delivery_task(order.id, schedule=timezone.now() + timezone.timedelta(minutes=preparation_time))
    else:
        send_pickup_notification_task(order.id, schedule=timezone.now() + timezone.timedelta(minutes=preparation_time))

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"restaurant_{slug}",
        {
            "type": "order_status_update",
            "order_id": order.id,
            "status": "PREPARING",
            "preparation_time": preparation_time,
        },
    )

    return JsonResponse({'success': True})

@require_POST
def mark_order_as_ready(request, slug, order_id):
    order = get_object_or_404(Order, id=order_id, restaurant__slug=slug)
    order.status = 'READY'
    order.save()

    if order.order_type == 'DELIVERY':
        create_delivery_task(order.id)
    else:
        send_pickup_notification_task(order.id)

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"restaurant_{slug}",
        {
            "type": "order_status_update",
            "order_id": order.id,
            "status": "READY",
        },
    )

    return JsonResponse({'success': True})


from .doordash_integration import check_delivery_distance


@require_POST
def check_delivery_distance_view(request, slug):
    data = json.loads(request.body)
    delivery_address = data.get('address')
    
    restaurant = get_object_or_404(Restaurant, slug=slug)
    restaurant_address = restaurant.address

    distance_miles, within_range = check_delivery_distance(restaurant_address, delivery_address)
    
    if within_range:
        # Calculate delivery fee
        base_fee = Decimal('9.75')  # Base fee for up to 5 miles
        additional_miles = max(0, min(distance_miles, 10) - 5)  # Cap at 10 miles
        additional_fee = Decimal('0.75') * Decimal(str(additional_miles))
        delivery_fee_usd = base_fee + additional_fee
        
        # Convert USD to AUD (let's assume an exchange rate of 1.5 for safety)
        exchange_rate = Decimal('1.5')
        delivery_fee_aud = (delivery_fee_usd * exchange_rate).quantize(Decimal('0.01'))
        
        return JsonResponse({
            'within_range': True,
            'distance_miles': round(distance_miles, 2),
            'distance_km': round(distance_miles * 1.60934, 2),
            'delivery_fee': str(delivery_fee_aud)
        })
    else:
        return JsonResponse({
            'within_range': False,
            'message': "Delivery address is outside of DoorDash's 10-mile delivery radius."
        })


import sys

@login_required
def loyalty_program_setup(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    if request.user.restaurant != restaurant and not request.user.is_superuser:
        messages.error(request, "You don't have permission to set up the loyalty program for this restaurant.")
        return redirect('restaurant_landing_page', slug=slug)

    if request.method == 'POST':
        program_type = request.POST.get('program_type')
        menu_item_points_multiplier = Decimal(request.POST.get('menu_item_points_multiplier', 10))

        print(f"Received POST data for {restaurant.name}:", file=sys.stderr)
        print(f"Program Type: {program_type}", file=sys.stderr)
        print(f"Menu Item Points Multiplier: {menu_item_points_multiplier}", file=sys.stderr)

        if program_type == 'PERCENTAGE':
            percentage = Decimal(request.POST.get('percentage', 0))
            points_per_100 = None
            print(f"Percentage: {percentage}%", file=sys.stderr)
        elif program_type == 'POINTS':
            points_per_100 = Decimal(request.POST.get('points_per_100', 0))
            percentage = None
            print(f"Points per 100 Dollars: {points_per_100}", file=sys.stderr)
        else:
            messages.error(request, "Invalid program type selected.")
            return redirect('loyalty_program_setup', slug=slug)

        loyalty_program, created = LoyaltyProgram.objects.update_or_create(
            restaurant=restaurant,
            defaults={
                'program_type': program_type,
                'percentage': percentage,
                'points_per_100': points_per_100,
                'menu_item_points_multiplier': menu_item_points_multiplier
            }
        )

        print(f"Loyalty Program {'created' if created else 'updated'} successfully", file=sys.stderr)

        messages.success(request, "Loyalty program has been updated successfully.")
        return redirect('restaurant_dashboard', slug=slug)
    
    loyalty_program = LoyaltyProgram.objects.filter(restaurant=restaurant).first()
    return render(request, 'restaurants/loyalty_program_setup.html', {'restaurant': restaurant, 'loyalty_program': loyalty_program})

@login_required
def digital_loyalty_card_setup(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    if request.method == 'POST':
        menu_item_id = request.POST.get('menu_item')
        buy_quantity = int(request.POST.get('buy_quantity', 4))
        free_quantity = int(request.POST.get('free_quantity', 1))
        menu_item = get_object_or_404(MenuItem, id=menu_item_id, menu__restaurant=restaurant)
        DigitalLoyaltyCard.objects.update_or_create(
            restaurant=restaurant,
            menu_item=menu_item,
            defaults={'buy_quantity': buy_quantity, 'free_quantity': free_quantity}
        )
        return redirect('restaurant_dashboard', slug=slug)
    
    menu_items = MenuItem.objects.filter(menu__restaurant=restaurant)
    digital_cards = DigitalLoyaltyCard.objects.filter(restaurant=restaurant)
    return render(request, 'restaurants/digital_loyalty_card_setup.html', 
                  {'restaurant': restaurant, 'menu_items': menu_items, 'digital_cards': digital_cards})

@login_required
def user_rewards(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    user_points, created = UserLoyaltyPoints.objects.get_or_create(user=request.user, restaurant=restaurant)
    menu_items = MenuItem.objects.filter(menu__restaurant=restaurant)
    digital_cards = UserDigitalCard.objects.filter(user=request.user, digital_card__restaurant=restaurant)
    
    return render(request, 'restaurants/user_rewards.html', 
                  {'restaurant': restaurant, 'user_points': user_points, 'menu_items': menu_items, 'digital_cards': digital_cards})


def calculate_loyalty_points(order):
    """
    Calculate loyalty points based on the order's total price and the restaurant's loyalty program.
    """
    restaurant = order.restaurant
    loyalty_program = LoyaltyProgram.objects.filter(restaurant=restaurant).first()
    if not loyalty_program:
        print(f"No loyalty program found for {restaurant.name}", file=sys.stderr)
        return Decimal('0.00')
    
    print(f"Calculating loyalty points for order {order.id}", file=sys.stderr)
    print(f"Order total: ${order.total_price}", file=sys.stderr)
    print(f"Loyalty Program Type: {loyalty_program.program_type}", file=sys.stderr)
    
    points_earned = loyalty_program.calculate_points_earned(order.total_price)
    
    print(f"Points earned: {points_earned}", file=sys.stderr)
    return points_earned

def redeem_points(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    menu_item_id = request.POST.get('menu_item_id')
    menu_item = get_object_or_404(MenuItem, id=menu_item_id, menu__restaurant=restaurant)

    user_points = UserLoyaltyPoints.objects.get(user=request.user, restaurant=restaurant)

    if user_points.points >= menu_item.points_price:
        user_points.points -= menu_item.points_price
        user_points.save()

        if menu_item.modifier_groups.exists():
            # Redirect to redeem_free_item_by_points if the item has modifiers
            return JsonResponse({
                'success': True,
                'redirect_url': reverse('redeem_free_item_by_menu_item', kwargs={'slug': slug, 'menu_item_id': menu_item_id})
            })
        else:
            # If no modifiers, directly create the cart item as free
            cart_item = CartItem.objects.create(
                menu_item=menu_item,
                user=request.user,
                restaurant=restaurant,
                quantity=1,
                notes="Redeemed with points",
                is_reward_item=True
            )
            return JsonResponse({
                'success': True,
                'message': 'Item added to cart successfully. Please proceed to checkout to complete your order.'
            })
    else:
        return JsonResponse({'success': False, 'message': 'Not enough points'})

def redeem_free_item_by_menu_item(request, slug, menu_item_id):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    menu_item = get_object_or_404(MenuItem, id=menu_item_id, menu__restaurant=restaurant)

    context = {
        'menu_item': menu_item,
        'restaurant': restaurant,
    }
    return render(request, 'restaurants/redeem_free_item_by_points.html', context)

@login_required
def confirm_redeem_by_points(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    menu_item_id = request.POST.get('menu_item_id')
    menu_item = get_object_or_404(MenuItem, id=menu_item_id, menu__restaurant=restaurant)

    print(f"Checking menuitem has modifiers: {'Yes' if menu_item.modifier_groups.exists() else 'No'}")
    print(f"Checking number of modifiers: {menu_item.modifier_groups.count()}")

    # Validate modifier selection
    for modifier_group in menu_item.modifier_groups.all():
        print(f"Checking {modifier_group.name} type: {modifier_group.selection_type}")
        print(f"Min selection for {modifier_group.name}: {modifier_group.min_selections}")
        print(f"Max selection for {modifier_group.name}: {modifier_group.max_selections or 'No limit'}")

        selected_modifiers = request.POST.getlist(f'modifier_group_{modifier_group.id}')
        print(f"Selected modifiers for {modifier_group.name}: {len(selected_modifiers)}")

        if len(selected_modifiers) < modifier_group.min_selections:
            messages.error(request, f"Please select at least {modifier_group.min_selections} {modifier_group.name}.")
            return redirect('redeem_free_item_by_menu_item', slug=slug, menu_item_id=menu_item_id)

        if modifier_group.max_selections and len(selected_modifiers) > modifier_group.max_selections:
            messages.error(request, f"You can select up to {modifier_group.max_selections} {modifier_group.name}.")
            return redirect('redeem_free_item_by_menu_item', slug=slug, menu_item_id=menu_item_id)

        for modifier_id in selected_modifiers:
            modifier = get_object_or_404(Modifier, id=modifier_id)
            print(f"Selected modifier for {modifier_group.name}: {modifier.name}")

    # Create the cart item with the redeemed item as free
    cart_item = CartItem.objects.create(
        menu_item=menu_item,
        user=request.user,
        restaurant=restaurant,
        quantity=1,
        notes="Redeemed with points",
        is_reward_item=True
    )

    # Handle selected modifiers
    for modifier_group in menu_item.modifier_groups.all():
        modifier_ids = request.POST.getlist(f'modifier_group_{modifier_group.id}')
        for modifier_id in modifier_ids:
            modifier = get_object_or_404(Modifier, id=modifier_id)
            CartItemModifier.objects.create(
                cart_item=cart_item,
                modifier=modifier
            )

    messages.success(request, f"You've successfully redeemed a free {menu_item.name}. It has been added to your cart.")
    return redirect('cart_view', slug=slug)

@require_http_methods(["POST"])
def redeem_digital_card(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    digital_card_id = request.POST.get('digital_card_id')
    digital_card = get_object_or_404(DigitalLoyaltyCard, id=digital_card_id, restaurant=restaurant)
    user_card = get_object_or_404(UserDigitalCard, user=request.user, digital_card=digital_card)
    
    print(f"Attempting to redeem digital card for {digital_card.menu_item.name}", file=sys.stderr)
    print(f"Current progress: {user_card.current_count} / {digital_card.buy_quantity}", file=sys.stderr)
    print(f"Current unredeemed rewards: {user_card.unredeemed_rewards}", file=sys.stderr)

    if user_card.unredeemed_rewards > 0:
        return redirect(reverse('redeem_free_item', kwargs={'slug': slug, 'digital_card_id': digital_card_id}))
    else:
        print("No rewards available for redemption.", file=sys.stderr)
        messages.error(request, "No rewards available for redemption.")
        return redirect('user_rewards', slug=slug)

def redeem_free_item(request, slug, digital_card_id):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    digital_card = get_object_or_404(DigitalLoyaltyCard, id=digital_card_id, restaurant=restaurant)
    menu_item = digital_card.menu_item
    
    context = {
        'menu_item': menu_item,
        'digital_card_id': digital_card_id,
        'restaurant': restaurant,
    }
    return render(request, 'restaurants/redeem_free_item.html', context)
    
def confirm_redeem_digital_card(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    digital_card_id = request.POST.get('digital_card_id')
    digital_card = get_object_or_404(DigitalLoyaltyCard, id=digital_card_id, restaurant=restaurant)
    user_card = get_object_or_404(UserDigitalCard, user=request.user, digital_card=digital_card)
    menu_item = digital_card.menu_item

    print(f"Checking menuitem has modifiers: {'Yes' if menu_item.modifier_groups.exists() else 'No'}")
    print(f"Checking number of modifiers: {menu_item.modifier_groups.count()}")

    # Validate modifier selection
    for modifier_group in menu_item.modifier_groups.all():
        print(f"Checking {modifier_group.name} type: {modifier_group.selection_type}")
        print(f"Min selection for {modifier_group.name}: {modifier_group.min_selections}")
        print(f"Max selection for {modifier_group.name}: {modifier_group.max_selections or 'No limit'}")

        selected_modifiers = request.POST.getlist(f'modifier_group_{modifier_group.id}')
        print(f"Selected modifiers for {modifier_group.name}: {len(selected_modifiers)}")

        if len(selected_modifiers) < modifier_group.min_selections:
            messages.error(request, f"Please select at least {modifier_group.min_selections} {modifier_group.name}.")
            return redirect('redeem_free_item', slug=slug, digital_card_id=digital_card_id)

        if modifier_group.max_selections and len(selected_modifiers) > modifier_group.max_selections:
            messages.error(request, f"You can select up to {modifier_group.max_selections} {modifier_group.name}.")
            return redirect('redeem_free_item', slug=slug, digital_card_id=digital_card_id)

        for modifier_id in selected_modifiers:
            modifier = get_object_or_404(Modifier, id=modifier_id)
            print(f"Selected modifier for {modifier_group.name}: {modifier.name}")

    if user_card.redeem_reward():
        # Create a new cart item for the redeemed menu item
        cart_item = CartItem.objects.create(
            menu_item=digital_card.menu_item,
            user=request.user,
            restaurant=restaurant,
            quantity=1,
            notes="Redeemed free item",
            is_reward_item=True
        )

        # Add selected modifiers
        for modifier_group in menu_item.modifier_groups.all():
            modifier_ids = request.POST.getlist(f'modifier_group_{modifier_group.id}')
            for modifier_id in modifier_ids:
                modifier = get_object_or_404(Modifier, id=modifier_id)
                CartItemModifier.objects.create(
                    cart_item=cart_item,
                    modifier=modifier
                )

        messages.success(request, f"You've successfully redeemed a free {digital_card.menu_item.name}. It has been added to your cart.")
        return redirect('cart_view', slug=slug)
    else:
        messages.error(request, "Failed to redeem reward. Please try again.")
        return redirect('user_rewards', slug=slug)
    

from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from django.http import HttpResponse
from django.conf import settings
import os
from collections import defaultdict


def generate_order_receipt_pdf(request, slug, order_id):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    order = get_object_or_404(Order, id=order_id, restaurant=restaurant)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    elements = []

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Center', alignment=1))

    # Add restaurant logo
    if restaurant.logo_image:
        logo_path = os.path.join(settings.MEDIA_ROOT, restaurant.logo_image.name)
        logo = Image(logo_path, width=2*inch, height=2*inch)
        elements.append(logo)

    # Add restaurant name and details
    elements.append(Paragraph(restaurant.name, styles['Title']))
    elements.append(Paragraph(restaurant.address, styles['Center']))
    elements.append(Paragraph(f"Phone: {restaurant.phone}", styles['Center']))
    elements.append(Spacer(1, 0.25*inch))

    # Add order details
    elements.append(Paragraph(f"Order #{order.id}", styles['Heading2']))
    elements.append(Paragraph(f"Date: {order.created_at.strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
    elements.append(Paragraph(f"Type: {order.get_order_type_display()}", styles['Normal']))
    if order.delivery_location:
        elements.append(Paragraph(f"Delivery Location: {order.delivery_location}", styles['Normal']))
    elements.append(Spacer(1, 0.25*inch))

    # Create table for order items
    data = [['Item', 'Quantity', 'Price']]
    for item in order.items.all():
        item_text = f"{item.menu_item.name}"
        if item.is_reward_item:
            item_text += " (Reward Item)"
        if item.notes:
            item_text += f"\n{item.notes}"
        data.append([
            Paragraph(item_text, styles['Normal']),
            str(item.quantity),
            f"${item.price:.2f}" if not item.is_reward_item else "FREE"
        ])
        for modifier in item.modifiers.all():
            data.append([
                Paragraph(f"  - {modifier.modifier.name}", styles['Normal']),
                "",
                f"${modifier.price:.2f}" if not item.is_reward_item else "FREE"
            ])

    # Add subtotal, delivery fee, and total price
    data.append(['', 'Subtotal:', f"${order.total_price:.2f}"])
    if order.delivery_fee > 0:
        data.append(['', 'Delivery Fee:', f"${order.delivery_fee:.2f}"])
        data.append(['', 'Store Contribution:', f"${order.store_contribution:.2f}"])
        data.append(['', 'Your Delivery Fee:', f"${order.customer_delivery_fee:.2f}"])
        if order.customer_delivery_fee == 0:
            data.append(['', 'Free Delivery Applied!', ''])
    data.append(['', 'Total:', f"${order.total_with_delivery:.2f}"])

    if order.loyalty_points_earned:
        data.append(['', 'Loyalty Points Earned:', f"{order.loyalty_points_earned:.2f}"])
    if order.loyalty_points_used:
        data.append(['', 'Loyalty Points Used:', f"{order.loyalty_points_used:.2f}"])

    # Create the table and set style
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 12),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))

    elements.append(table)

    # Add powered by text
    elements.append(Spacer(1, 0.5*inch))
    elements.append(Paragraph("Powered by Bite - A Nexa Digital Product", styles['Center']))

    # Build the PDF
    doc.build(elements)

    # Get the value of the BytesIO buffer and write it to the response
    pdf = buffer.getvalue()
    buffer.close()
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="order_{order.id}_receipt.pdf"'
    response.write(pdf)
    return response

@login_required
def weekly_sales_report(request, slug, week_start):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    if request.user.restaurant != restaurant and not request.user.is_superuser:
        messages.error(request, "You don't have permission to view this report.")
        return redirect('restaurant_landing_page', slug=slug)

    week_start = timezone.datetime.strptime(week_start, "%Y-%m-%d").date()
    week_end = week_start + timezone.timedelta(days=6)
    weekly_sales = get_object_or_404(WeeklySales, restaurant=restaurant, week_start=week_start)

    # Fetch all orders for the week
    orders = Order.objects.filter(restaurant=restaurant, created_at__date__range=[week_start, week_end]).order_by('created_at')

    # Group orders by day
    daily_orders = defaultdict(list)
    daily_totals = defaultdict(Decimal)
    daily_delivery_fees = defaultdict(Decimal)
    daily_store_contributions = defaultdict(Decimal)
    daily_customer_delivery_fees = defaultdict(Decimal)

    for order in orders:
        day = order.created_at.strftime("%A")
        daily_orders[day].append(order)
        daily_totals[day] += order.total_price
        daily_delivery_fees[day] += order.delivery_fee
        daily_store_contributions[day] += order.store_contribution
        daily_customer_delivery_fees[day] += order.customer_delivery_fee

    # Generate PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    elements = []

    styles = getSampleStyleSheet()
    elements.append(Paragraph(f"{restaurant.name} - Weekly Sales Report", styles['Title']))
    elements.append(Paragraph(f"Week of {week_start.strftime('%B %d, %Y')} - {week_end.strftime('%B %d, %Y')}", styles['Heading2']))
    elements.append(Spacer(1, 12))

    grand_total = Decimal('0.00')
    grand_delivery_fees = Decimal('0.00')
    grand_store_contributions = Decimal('0.00')
    grand_customer_delivery_fees = Decimal('0.00')

    for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']:
        elements.append(Paragraph(day, styles['Heading3']))
        if day in daily_orders:
            data = [['Order ID', 'Time', 'Subtotal', 'Delivery Fee', 'Store Contribution', 'Customer Fee', 'Total']]
            for order in daily_orders[day]:
                data.append([
                    str(order.id), 
                    order.created_at.strftime('%H:%M'), 
                    f"${order.total_price:.2f}",
                    f"${order.delivery_fee:.2f}",
                    f"${order.store_contribution:.2f}",
                    f"${order.customer_delivery_fee:.2f}",
                    f"${order.total_with_delivery:.2f}"
                ])
            table = Table(data)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('TOPPADDING', (0, 1), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            elements.append(table)
            elements.append(Paragraph(f"Daily Subtotal: ${daily_totals[day]:.2f}", styles['Normal']))
            elements.append(Paragraph(f"Daily Delivery Fees: ${daily_delivery_fees[day]:.2f}", styles['Normal']))
            elements.append(Paragraph(f"Daily Store Contributions: ${daily_store_contributions[day]:.2f}", styles['Normal']))
            elements.append(Paragraph(f"Daily Customer Delivery Fees: ${daily_customer_delivery_fees[day]:.2f}", styles['Normal']))
            elements.append(Paragraph(f"Daily Total: ${(daily_totals[day] + daily_customer_delivery_fees[day]):.2f}", styles['Normal']))
        else:
            elements.append(Paragraph("(no orders)", styles['Normal']))
        elements.append(Spacer(1, 12))
        grand_total += daily_totals[day]
        grand_delivery_fees += daily_delivery_fees[day]
        grand_store_contributions += daily_store_contributions[day]
        grand_customer_delivery_fees += daily_customer_delivery_fees[day]

    elements.append(Paragraph("Weekly Summary", styles['Heading2']))
    summary_data = [['Day', 'Subtotal', 'Delivery Fees', 'Store Contributions', 'Customer Fees', 'Total']]
    for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']:
        summary_data.append([
            day, 
            f"${daily_totals[day]:.2f}", 
            f"${daily_delivery_fees[day]:.2f}",
            f"${daily_store_contributions[day]:.2f}",
            f"${daily_customer_delivery_fees[day]:.2f}",
            f"${(daily_totals[day] + daily_customer_delivery_fees[day]):.2f}"
        ])
    summary_data.append([
        'Weekly Total', 
        f"${grand_total:.2f}", 
        f"${grand_delivery_fees:.2f}", 
        f"${grand_store_contributions:.2f}", 
        f"${grand_customer_delivery_fees:.2f}", 
        f"${(grand_total + grand_customer_delivery_fees):.2f}"
    ])
    summary_table = Table(summary_data)
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ALIGN', (0, 1), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (-1, -1), (-1, -1), colors.lightblue),
        ('FONTNAME', (-1, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    elements.append(summary_table)

    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{restaurant.name}_weekly_report_{week_start}.pdf"'
    response.write(pdf)
    return response


from .sms_sender import send_sms

@require_POST
def send_sms_to_subscribers(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    if request.user.restaurant != restaurant and not request.user.is_superuser:
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    message = request.POST.get('smsMessage')
    selected_subscribers = request.POST.getlist('selectedSubscribers')

    if not message or not selected_subscribers:
        return JsonResponse({'success': False, 'error': 'Message and subscribers are required'}, status=400)

    success_count = 0
    error_count = 0

    for subscriber_id in selected_subscribers:
        subscriber = Subscription.objects.get(id=subscriber_id, restaurant=restaurant)
        success, result = send_sms(subscriber.phone, message)
        if success:
            success_count += 1
        else:
            error_count += 1

    return JsonResponse({
        'success': True,
        'message': f'SMS sent successfully to {success_count} subscribers. {error_count} failed.'
    })