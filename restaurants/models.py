from django.db import models
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.utils.text import slugify
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify

class Restaurant(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    description = models.TextField()
    landing_page_tagline = models.TextField()
    landing_page_image = models.ImageField(upload_to='restaurant_images/')
    address = models.CharField(max_length=255, null=True)
    phone = models.CharField(max_length=20, null=True)
    logo_image = models.ImageField(upload_to='restaurant_images/')
    primary_color = models.CharField(max_length=7)  # Hex color code
    favicon = models.FileField(upload_to='restaurant_favicons/', null=True, blank=True)
    about_us_image1 = models.ImageField(upload_to='restaurant_images/')
    about_us_text1 = models.TextField(blank=True, null=True)
    about_us_image2 = models.ImageField(upload_to='restaurant_images/')
    about_us_text2 = models.TextField(blank=True, null=True)
    about_us_image3 = models.ImageField(upload_to='restaurant_images/')
    about_us_text3 = models.TextField(blank=True, null=True)
    contact_us_image = models.ImageField(upload_to='restaurant_images/')
    map_iframe_src = models.TextField(blank=True, null=True)
    footer_text = models.TextField()
    facebook_link = models.URLField(null=True, blank=True)
    instagram_link = models.URLField(null=True, blank=True)
    youtube_link = models.URLField(null=True, blank=True)
    twitter_link = models.URLField(null=True, blank=True)
    slug = models.SlugField(unique=True, max_length=100, null=True, blank=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_account_id = models.CharField(max_length=255, blank=True, null=True)
    doordash_external_business_id = models.CharField(max_length=255, blank=True, null=True)
    doordash_external_store_id = models.CharField(max_length=255, blank=True, null=True)
    delivery_fee_contribution = models.BooleanField(default=False)
    delivery_fee_contribution_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    free_delivery_threshold = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_accepting_orders = models.BooleanField(default=True)

    DAYS_OF_WEEK = [
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
        ('public_holidays', 'Public Holidays'),
    ]

    # Add these fields for each day
    for day, _ in DAYS_OF_WEEK:
        locals()[f'{day}_open'] = models.TimeField(null=True, blank=True)
        locals()[f'{day}_close'] = models.TimeField(null=True, blank=True)
        locals()[f'is_{day}_closed'] = models.BooleanField(default=False)

    def clean(self):
        for day, _ in self.DAYS_OF_WEEK:
            open_time = getattr(self, f'{day}_open')
            close_time = getattr(self, f'{day}_close')
            is_closed = getattr(self, f'is_{day}_closed')

            if is_closed:
                if open_time or close_time:
                    raise ValidationError(f"{day.capitalize()} is marked as closed but has opening/closing times.")
            else:
                if not open_time or not close_time:
                    raise ValidationError(f"{day.capitalize()} must have both opening and closing times if not marked as closed.")
                
    def get_formatted_hours(self):
        formatted_hours = {}
        for day, day_name in self.DAYS_OF_WEEK:
            is_closed = getattr(self, f'is_{day}_closed')
            if is_closed:
                formatted_hours[day_name] = 'Closed'
            else:
                open_time = getattr(self, f'{day}_open')
                close_time = getattr(self, f'{day}_close')
                if open_time and close_time:
                    formatted_hours[day_name] = f'{open_time.strftime("%H:%M")} - {close_time.strftime("%H:%M")}'
                else:
                    formatted_hours[day_name] = 'Not set'
        return formatted_hours

    def save(self, *args, **kwargs):
        # Auto-generate the slug from the name if it's not set or if the name has changed
        if not self.slug:
            self.slug = slugify(self.name)
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class RestaurantUser(AbstractUser):
    restaurant = models.OneToOneField('Restaurant', on_delete=models.CASCADE, null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    is_restaurant_admin = models.BooleanField(default=False)

    groups = models.ManyToManyField(
        Group,
        related_name='restaurantuser_set',
        blank=True,
        help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.',
        related_query_name='restaurantuser',
    )
    user_permissions = models.ManyToManyField(
        Permission,
        related_name='restaurantuser_set',
        blank=True,
        help_text='Specific permissions for this user.',
        related_query_name='restaurantuser',
    )

    def save(self, *args, **kwargs):
        if self.is_restaurant_admin:
            self.is_staff = True
        super().save(*args, **kwargs)

class Subscription(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE)
    user = models.ForeignKey(RestaurantUser, on_delete=models.CASCADE)
    email = models.EmailField()
    phone = models.CharField(max_length=20, null=True, blank=True)
    subscribed = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.email} - {self.restaurant.name}"
    
class Menu(models.Model):
    restaurant = models.ForeignKey('Restaurant', on_delete=models.CASCADE, related_name='menus')
    image = models.ImageField(upload_to='menus/', null=True, blank=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.restaurant.name} - {self.name}"


class MenuItem(models.Model):
    menu = models.ForeignKey(Menu, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    image1 = models.ImageField(upload_to='menu_items/', null=True, blank=True)
    image2 = models.ImageField(upload_to='menu_items/', null=True, blank=True)
    image3 = models.ImageField(upload_to='menu_items/', null=True, blank=True)
    points_price = models.PositiveIntegerField(null=True, blank=True)
    has_required_modifiers = models.BooleanField(default=False)

    def calculate_points_price(self):
        """
        Calculate the points price based on the restaurant's loyalty program.
        """
        loyalty_program = self.menu.restaurant.loyalty_program
        if not loyalty_program:
            print(f"No loyalty program found for {self.menu.restaurant.name}. Returning 0 points.", file=sys.stderr)
            return 0

        try:
            price = Decimal(self.price)
            multiplier = Decimal(loyalty_program.menu_item_points_multiplier)
            points_price = int(price * multiplier)
            print(f"Item: {self.name}, Price: ${price}, "
                  f"Multiplier: {multiplier}, "
                  f"Points Price (calculated): {points_price} points", file=sys.stderr)
            return points_price
        except Exception as e:
            print(f"Error calculating points price for {self.name}: {str(e)}", file=sys.stderr)
            return 0

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.points_price = self.calculate_points_price()
        # Check if any modifier groups are required
        if self.modifier_groups.filter(min_selections__gt=0).exists():
            self.has_required_modifiers = True
        else:
            self.has_required_modifiers = False
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.menu.name} - {self.name}"

@receiver(post_save, sender='restaurants.LoyaltyProgram')
def update_menu_item_points(sender, instance, **kwargs):
    print(f"Updating menu item points for {instance.restaurant.name}", file=sys.stderr)
    for menu in instance.restaurant.menus.all():
        for item in menu.items.all():
            item.save()  # This will trigger the MenuItem's save method, which recalculates the points_price
    print("Menu item points updated and saved", file=sys.stderr)

class ModifierGroup(models.Model):
    SELECTION_TYPE_CHOICES = [
        ('SINGLE', 'Single Select'),
        ('MULTIPLE', 'Multiple Select'),
    ]

    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE, related_name='modifier_groups')
    name = models.CharField(max_length=100)
    selection_type = models.CharField(max_length=10, choices=SELECTION_TYPE_CHOICES)
    min_selections = models.PositiveIntegerField(default=0)
    max_selections = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.menu_item.name} - {self.name}"

class Modifier(models.Model):
    group = models.ForeignKey(ModifierGroup, on_delete=models.CASCADE, related_name='modifiers')
    name = models.CharField(max_length=100)
    price_varies = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, null=True, blank=True)

    def __str__(self):
        return f"{self.group.name} - {self.name}"


class CartItem(models.Model):
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    user = models.ForeignKey(RestaurantUser, on_delete=models.CASCADE, null=True, blank=True)
    guest_phone = models.CharField(max_length=20, null=True, blank=True)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_reward_item = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.quantity}x {self.menu_item.name}"

    @property
    def total_price(self):
        if self.is_reward_item:
            return Decimal('0.00')
        item_price = self.menu_item.price
        for modifier in self.selected_modifiers.all():
            item_price += modifier.modifier.price
        return item_price * self.quantity 

class CartItemModifier(models.Model):
    cart_item = models.ForeignKey(CartItem, on_delete=models.CASCADE, related_name='selected_modifiers')
    modifier = models.ForeignKey(Modifier, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.cart_item} - {self.modifier.name}"



class WeeklySales(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE)
    week_start = models.DateField()
    week_end = models.DateField()
    total_sales = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_delivery_fees = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_store_contributions = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_customer_delivery_fees = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_paid = models.BooleanField(default=False)
    stripe_transfer_id = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"{self.restaurant.name} - Week of {self.week_start}"

    @property
    def grand_total(self):
        return self.total_sales + self.total_customer_delivery_fees

    def update_totals(self):
        orders = Order.objects.filter(
            restaurant=self.restaurant,
            created_at__date__range=[self.week_start, self.week_end]
        )
        self.total_sales = sum(order.total_price for order in orders)
        self.total_delivery_fees = sum(order.delivery_fee for order in orders)
        self.total_store_contributions = sum(order.store_contribution for order in orders)
        self.total_customer_delivery_fees = sum(order.customer_delivery_fee for order in orders)
        self.save()

    @classmethod
    def get_or_create_current_week(cls, restaurant):
        today = timezone.now().date()
        week_start = today - timezone.timedelta(days=today.weekday())
        week_end = week_start + timezone.timedelta(days=6)
        return cls.objects.get_or_create(
            restaurant=restaurant,
            week_start=week_start,
            week_end=week_end
        )


class Order(models.Model):
    ORDER_TYPE_CHOICES = [
        ('TAKEOUT', 'Takeout'),
        ('PICKUP', 'Pickup/Eat-in'),
        ('DELIVERY', 'Delivery'),
    ]
    ORDER_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('PREPARING', 'Preparing'),
        ('READY', 'Ready'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE)
    user = models.ForeignKey(RestaurantUser, on_delete=models.SET_NULL, null=True, blank=True)
    guest_phone = models.CharField(max_length=20, null=True, blank=True)
    order_type = models.CharField(max_length=10, choices=ORDER_TYPE_CHOICES)
    delivery_location = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(max_length=10, choices=ORDER_STATUS_CHOICES, default='PENDING')
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    stripe_payment_intent_id = models.CharField(max_length=255, null=True, blank=True)
    stripe_transfer_id = models.CharField(max_length=255, null=True, blank=True)
    doordash_order_id = models.CharField(max_length=255, null=True, blank=True)
    preparation_time = models.IntegerField(null=True, blank=True)  # in minutes
    preparation_start_time = models.DateTimeField(null=True, blank=True)
    doordash_delivery_id = models.CharField(max_length=255, null=True, blank=True)
    loyalty_points_earned = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    loyalty_points_used = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    weekly_sales = models.ForeignKey(WeeklySales, on_delete=models.SET_NULL, null=True, blank=True)
    sms_sent = models.BooleanField(default=False)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    customer_delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    store_contribution = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    @property
    def total_with_delivery(self):
        return self.total_price + self.customer_delivery_fee

    @property
    def net_payout(self):
        return self.total_price + self.delivery_fee - self.store_contribution

    def __str__(self):
        return f"Order {self.id} - {self.restaurant.name}"
    
    def save(self, *args, **kwargs):
        if not self.weekly_sales:
            self.weekly_sales, _ = WeeklySales.get_or_create_current_week(self.restaurant)
        super().save(*args, **kwargs)


class OrderNotification(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notification for Order {self.order.id}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True, null=True)
    is_reward_item = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.quantity}x {self.menu_item.name} for Order {self.order.id}"

class OrderItemModifier(models.Model):
    order_item = models.ForeignKey(OrderItem, related_name='modifiers', on_delete=models.CASCADE)
    modifier = models.ForeignKey(Modifier, on_delete=models.CASCADE)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.modifier.name} for {self.order_item}"
    
import sys
from decimal import Decimal


class LoyaltyProgram(models.Model):
    PROGRAM_TYPES = (
        ('PERCENTAGE', 'Percentage'),
        ('POINTS', 'Points per 100 Dollars'),
    )
    restaurant = models.OneToOneField('Restaurant', on_delete=models.CASCADE, related_name='loyalty_program')
    program_type = models.CharField(max_length=10, choices=PROGRAM_TYPES)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    points_per_100 = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    menu_item_points_multiplier = models.DecimalField(max_digits=5, decimal_places=2, default=10)

    def clean(self):
        if self.program_type == 'PERCENTAGE' and not self.percentage:
            raise ValidationError("Percentage is required for percentage-type program")
        if self.program_type == 'POINTS' and not self.points_per_100:
            raise ValidationError("Points per 100 dollars is required for points-type program")

    def save(self, *args, **kwargs):
        print(f"Saving Loyalty Program for {self.restaurant.name}", file=sys.stderr)
        print(f"Program Type: {self.program_type}", file=sys.stderr)
        if self.program_type == 'PERCENTAGE':
            print(f"Percentage: {self.percentage}%", file=sys.stderr)
        else:
            print(f"Points per 100 Dollars: {self.points_per_100}", file=sys.stderr)
        print(f"Menu Item Points Multiplier: {self.menu_item_points_multiplier}", file=sys.stderr)

        super().save(*args, **kwargs)
        self.update_menu_item_points()

    def update_menu_item_points(self):
        print(f"Updating menu item points for {self.restaurant.name}", file=sys.stderr)
        for menu in self.restaurant.menus.all():
            for item in menu.items.all():
                item.save()  # This will trigger the MenuItem's save method, which recalculates the points_price
        print("Menu item points updated and saved", file=sys.stderr)

    def calculate_points_earned(self, purchase_amount):
        print(f"Calculating points for purchase amount: ${purchase_amount}", file=sys.stderr)
        if self.program_type == 'PERCENTAGE':
            points = purchase_amount * (self.percentage / 100)
            print(f"Percentage program: {self.percentage}% of ${purchase_amount}", file=sys.stderr)
        else:  # POINTS
            points_per_dollar = self.points_per_100 / 100
            points = purchase_amount * points_per_dollar
            print(f"Points program: {self.points_per_100} points per $100 (${points_per_dollar} per $1) for ${purchase_amount}", file=sys.stderr)
        
        points = Decimal(points).quantize(Decimal('0.01'))
        print(f"Final points earned: {points}", file=sys.stderr)
        return points

    def __str__(self):
        return f"{self.restaurant.name} Loyalty Program"

class DigitalLoyaltyCard(models.Model):
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, related_name='digital_loyalty_cards')
    menu_item = models.ForeignKey(MenuItem, on_delete=models.CASCADE)
    buy_quantity = models.PositiveIntegerField(default=4)
    free_quantity = models.PositiveIntegerField(default=1)


class UserLoyaltyPoints(models.Model):
    user = models.ForeignKey(RestaurantUser, on_delete=models.CASCADE)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE)
    points = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.user.username}'s points for {self.restaurant.name}: {self.points}"

    def add_points(self, points_to_add):
        self.points += Decimal(points_to_add).quantize(Decimal('0.01'))
        self.save()

    def use_points(self, points_to_use):
        if self.points >= points_to_use:
            self.points -= Decimal(points_to_use).quantize(Decimal('0.01'))
            self.save()
            return True
        return False


class UserDigitalCard(models.Model):
    user = models.ForeignKey(RestaurantUser, on_delete=models.CASCADE)
    digital_card = models.ForeignKey('DigitalLoyaltyCard', on_delete=models.CASCADE)
    current_count = models.PositiveIntegerField(default=0)
    unredeemed_rewards = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.user.username}'s {self.digital_card.menu_item.name} Card"

    def add_purchase(self, quantity):
        print(f"Adding purchase of {quantity} {self.digital_card.menu_item.name}(s)", file=sys.stderr)
        print(f"Current count before purchase: {self.current_count}", file=sys.stderr)
        print(f"Unredeemed rewards before purchase: {self.unredeemed_rewards}", file=sys.stderr)

        self.current_count += quantity
        print(f"New count after purchase: {self.current_count}", file=sys.stderr)
        
        while self.current_count >= self.digital_card.buy_quantity:
            earned_rewards = self.current_count // self.digital_card.buy_quantity
            self.unredeemed_rewards += earned_rewards * self.digital_card.free_quantity
            self.current_count %= self.digital_card.buy_quantity
            
            print(f"Fulfilled the counter {self.current_count}/{self.digital_card.buy_quantity}", file=sys.stderr)
            print(f"Customer earns {earned_rewards * self.digital_card.free_quantity} free {self.digital_card.menu_item.name}(s)", file=sys.stderr)
            print(f"New unredeemed rewards: {self.unredeemed_rewards}", file=sys.stderr)
            print(f"Remaining count: {self.current_count}", file=sys.stderr)

        self.save()

    def redeem_reward(self):
        print(f"Attempting to redeem a reward for {self.digital_card.menu_item.name}", file=sys.stderr)
        print(f"Current unredeemed rewards: {self.unredeemed_rewards}", file=sys.stderr)

        if self.unredeemed_rewards > 0:
            self.unredeemed_rewards -= 1
            self.save()
            print(f"Reward redeemed. Remaining unredeemed rewards: {self.unredeemed_rewards}", file=sys.stderr)
            return True
        else:
            print("No rewards available to redeem", file=sys.stderr)
            return False

    def reset_if_all_redeemed(self):
        print(f"Checking if all rewards for {self.digital_card.menu_item.name} have been redeemed", file=sys.stderr)
        print(f"Current unredeemed rewards: {self.unredeemed_rewards}", file=sys.stderr)
        print(f"Current count: {self.current_count}", file=sys.stderr)

        if self.unredeemed_rewards == 0:
            self.current_count = 0
            self.save()
            print("All rewards redeemed. Counter reset to 0.", file=sys.stderr)
        else:
            print("Unredeemed rewards remain. Counter not reset.", file=sys.stderr)
