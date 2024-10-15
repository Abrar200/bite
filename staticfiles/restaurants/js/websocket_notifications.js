// Create a new file named websocket_notifications.js in your static/js directory

const restaurantSlug = document.body.dataset.restaurantSlug;
const wsScheme = window.location.protocol === "https:" ? "wss" : "ws";
const wsPath = `${wsScheme}://${window.location.host}/ws/orders/${restaurantSlug}/`;
const socket = new WebSocket(wsPath);

socket.onmessage = function(e) {
    const data = JSON.parse(e.data);
    if (data.type === 'order_notification') {
        // Play notification sound
        const audio = new Audio('/static/sounds/notification.mp3');
        audio.play();

        // Show notification
        showNotification(data.message);

        // Update order list in the dashboard
        updateOrderList();
    } else if (data.type === 'preparation_time_update') {
        // Update the preparation time for the specific order
        updatePreparationTime(data.order_id, data.preparation_time);
    }
};

socket.onclose = function(e) {
    console.error('WebSocket closed unexpectedly');
};

function showNotification(message) {
    // You can implement this function to show a notification on the dashboard
    // For example, you could use a library like toastr or create a custom notification
    alert(message);  // Replace this with a more user-friendly notification
}

function updateOrderList() {
    // Implement this function to refresh the order list on the dashboard
    // You might want to make an AJAX call to get the updated list of orders
    location.reload();  // For simplicity, we're just reloading the page
}

function updatePreparationTime(orderId, preparationTime) {
    // Update the preparation time display for the specific order
    const timerElement = document.querySelector(`#order-${orderId} .preparation-timer`);
    if (timerElement) {
        timerElement.textContent = `Preparation time: ${preparationTime} minutes`;
    }
}