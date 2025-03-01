import streamlit as st
import google.generativeai as genai
import os
import pandas as pd
import re
import time

# Set up API Key
os.environ["GOOGLE_API_KEY"] = "AIzaSyCmTMP93DcIA0UlXIkpsPaydTJ4bX5FYDI"
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
model = genai.GenerativeModel("gemini-1.5-pro-latest")


# Function to fetch vehicle details with rate limiting and better error handling
def get_vehicle_info(vehicle_name):
    prompt = f"""
    Provide detailed specifications of {vehicle_name} in the following format:
    Range: <value in miles or km>
    Price: <value in $ with numbers only>
    Horsepower: <numeric value>
    Features: <comma-separated list>
    
    For non-electric vehicles, you can put 'N/A' for Range.
    For price, give a specific number like '$40000' without commas.
    For horsepower, give a specific number like '250'.
    Only return the information in the exact format above without extra text.
    """
    try:
        response = model.generate_content(prompt)
        return response.text.strip() if response.text else "Data not available"
    except Exception as e:
        st.warning(f"API call failed: {str(e)}. Using fallback data.")
        return f"""
        Range: 300 miles
        Price: $40000
        Horsepower: 250
        Features: Air Conditioning, Bluetooth, Cruise Control, Navigation
        """

# Function to parse response into structured data
def parse_vehicle_info(response_text):
    data = {"Range": "N/A", "Price": "N/A", "Horsepower": "N/A", "Features": "N/A"}
    for line in response_text.split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            key, value = key.strip(), value.strip()
            if key in data:
                data[key] = value
    return data

# Helper function to extract numeric values from specification strings
def extract_numeric_value(value_str):
    if value_str == "N/A":
        return 0
    
    # Try to extract the first number from the string
    numbers = re.findall(r'\d+(?:\.\d+)?', value_str)
    if numbers:
        return float(numbers[0])
    return 0

# Function to determine the better vehicle
def determine_best_vehicle(v1_name, v1_data, v2_name, v2_data):
    criteria = ["Range", "Price", "Horsepower"]
    scores = {v1_name: 0, v2_name: 0}
    comparison_reasons = []

    for criterion in criteria:
        try:
            # Extract numeric values for comparison
            v1_value = extract_numeric_value(v1_data[criterion])
            v2_value = extract_numeric_value(v2_data[criterion])

            if criterion == "Price":  # Lower price is better
                if v1_value < v2_value and v1_value > 0:
                    scores[v1_name] += 1
                    comparison_reasons.append(f"{v1_name} has a lower price (${v1_value} vs ${v2_value})")
                elif v2_value < v1_value and v2_value > 0:
                    scores[v2_name] += 1
                    comparison_reasons.append(f"{v2_name} has a lower price (${v2_value} vs ${v1_value})")
                else:
                    comparison_reasons.append(f"Both vehicles have similar price")
            else:  # Higher is better for Range & Horsepower
                if v1_value > v2_value and v1_value > 0:
                    scores[v1_name] += 1
                    comparison_reasons.append(f"{v1_name} has better {criterion.lower()} ({v1_value} vs {v2_value})")
                elif v2_value > v1_value and v2_value > 0:
                    scores[v2_name] += 1
                    comparison_reasons.append(f"{v2_name} has better {criterion.lower()} ({v2_value} vs {v1_value})")
                else:
                    comparison_reasons.append(f"Both vehicles have similar {criterion.lower()}")
        except Exception as e:
            comparison_reasons.append(f"Could not compare {criterion} (insufficient data)")

    winner = v1_name if scores[v1_name] >= scores[v2_name] else v2_name
    return winner, comparison_reasons

# Function to get top vehicles based on filters with better fallback and error handling
def get_top_vehicles(vehicle_type, brand, min_price, max_price, fuel_type):
    # Check if we have cached results
    cache_key = f"{vehicle_type}_{brand}_{min_price}_{max_price}_{fuel_type}"
    if "vehicle_cache" in st.session_state and cache_key in st.session_state.vehicle_cache:
        return st.session_state.vehicle_cache[cache_key]
    
    brand_text = f"from {brand}" if brand != "All Brands" else ""
    prompt = f"""
    List the top 10 {fuel_type} {vehicle_type}s {brand_text} priced between ${min_price} - ${max_price}.
    Return results in this exact format as a JSON-like structure:
    [
      {{"Name": "Full Vehicle Name", "Price": "Price in $", "Range": "Range in miles or N/A", "Fuel": "{fuel_type}", "Horsepower": "HP value"}},
      ... (repeat for all vehicles)
    ]
    
    For electric vehicles, include range in miles. For non-electric, range should be "N/A".
    Only return the structured data without any other text.
    """
    
    # Initialize fallback data based on input parameters
    fallback_data = []
    
    if brand == "All Brands" or brand == "":
        brands_to_use = ["Toyota", "Honda", "Ford"] if vehicle_type == "4-Wheeler" else ["Yamaha", "Honda", "Kawasaki"]
    else:
        brands_to_use = [brand]
    
    # Create realistic fallback data
    base_price = min_price
    price_increment = (max_price - min_price) / 10 if max_price > min_price else 5000
    
    for i in range(1, 11):
        model_type = "SUV" if i % 3 == 0 else "Sedan" if i % 3 == 1 else "Crossover"
        if vehicle_type == "2-Wheeler":
            model_type = "Sport" if i % 3 == 0 else "Cruiser" if i % 3 == 1 else "Touring"
        
        brand_to_use = brands_to_use[i % len(brands_to_use)]
        price = int(base_price + (i * price_increment))
        hp = 150 + (i * 25)
        range_val = f"{200 + (i * 20)} miles" if fuel_type == "Electric" else "N/A"
        
        fallback_data.append({
            "Name": f"{brand_to_use} {model_type} {2023 + (i % 3)}",
            "Price": f"${price:,d}",
            "Range": range_val,
            "Fuel": fuel_type,
            "Horsepower": f"{hp} HP"
        })
    
    try:
        # Try to get data from API with backoff
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                response = model.generate_content(prompt)
                response_text = response.text.strip()
                
                # Extract the JSON-like content
                if "```" in response_text:
                    response_text = response_text.split("```")[1]
                    if response_text.startswith("json"):
                        response_text = response_text[4:].strip()
                
                # Try to safely evaluate the string as Python expression
                import ast
                try:
                    vehicles = ast.literal_eval(response_text)
                    # Cache the result
                    if "vehicle_cache" not in st.session_state:
                        st.session_state.vehicle_cache = {}
                    st.session_state.vehicle_cache[cache_key] = vehicles
                    return vehicles
                except:
                    # If parsing fails, increment retry count
                    retry_count += 1
                    if retry_count >= max_retries:
                        st.warning("Could not parse vehicle data from API, using fallback data")
                        return fallback_data
                    time.sleep(2)  # Wait before retrying
            except Exception as e:
                error_message = str(e)
                if "429" in error_message:
                    st.warning("API rate limit exceeded. Using fallback data instead.")
                    return fallback_data
                
                # Increment retry count
                retry_count += 1
                if retry_count >= max_retries:
                    st.warning(f"API error after {max_retries} attempts: {error_message}. Using fallback data.")
                    return fallback_data
                time.sleep(2)  # Wait before retrying
        
        # If we get here, all retries failed
        return fallback_data
    except Exception as e:
        st.error(f"Error fetching vehicles: {str(e)}")
        return fallback_data

# List of common vehicle brands for dropdown
CAR_BRANDS = [
    "All Brands",
    "Acura", "Alfa Romeo", "Aston Martin", "Audi", "Bentley", "BMW", "Bugatti", 
    "Buick", "Cadillac", "Chevrolet", "Chrysler", "Citroën", "Dodge", "Ferrari", 
    "Fiat", "Ford", "Genesis", "GMC", "Honda", "Hyundai", "Infiniti", "Jaguar", 
    "Jeep", "Kia", "Lamborghini", "Land Rover", "Lexus", "Lincoln", "Lotus", 
    "Maserati", "Mazda", "McLaren", "Mercedes-Benz", "Mini", "Mitsubishi", 
    "Nissan", "Porsche", "Ram", "Rolls-Royce", "Subaru", "Tesla", "Toyota", 
    "Volkswagen", "Volvo"
]

MOTORCYCLE_BRANDS = [
    "All Brands",
    "Aprilia", "BMW", "Ducati", "Harley-Davidson", "Honda", "Indian", "Kawasaki", 
    "KTM", "Moto Guzzi", "MV Agusta", "Royal Enfield", "Suzuki", "Triumph", 
    "Vespa", "Yamaha", "Zero"
]

# Get list of brands based on vehicle type
def get_vehicle_brands(vehicle_type):
    if vehicle_type == "2-Wheeler":
        return MOTORCYCLE_BRANDS
    else:  # "4-Wheeler"
        return CAR_BRANDS

# Streamlit App
st.set_page_config(page_title="AutoSage", page_icon="🚗", layout="wide")

# Initialize session state variables
if "selected_vehicle_type" not in st.session_state:
    st.session_state.selected_vehicle_type = "4-Wheeler"
if "brand_options" not in st.session_state:
    st.session_state.brand_options = get_vehicle_brands("4-Wheeler")
if "selected_brand" not in st.session_state:
    st.session_state.selected_brand = "All Brands"
if "vehicle_cache" not in st.session_state:
    st.session_state.vehicle_cache = {}

# Update brand options when vehicle type changes
def update_brand_options():
    st.session_state.brand_options = get_vehicle_brands(st.session_state.selected_vehicle_type)
    st.session_state.selected_brand = "All Brands"

# Sidebar Navigation
st.sidebar.title("🚗 AutoSage Navigation")
page = st.sidebar.radio("Go to", ["Home", "Explore", "Compare","Regular maintenance tips","Rental Services","AutoSage Bot"])

if page == "Home":
    st.title("🚗 Welcome to AutoSage!")
    st.subheader("Your AI-Powered Vehicle Comparison & Exploration Tool")
    st.write("Use AutoSage to explore vehicles, compare them, and find the best one suited for you.")
    
    # Add information about API usage
    st.info("📢 Note: This app uses the Google Generative AI API which has rate limits. If you encounter '429 Resource Exhausted' errors, the app will automatically fall back to pre-generated data.")


elif page =="Regular maintenance tips":
    st.subheader("📋 Routine Maintenance Checklist")
    st.write("Follow these steps to ensure your vehicle stays in top condition:")

    maintenance_tasks = [
        "Check and change engine oil regularly",
        "Inspect and replace air filters",
        "Keep tires properly inflated and aligned",
        "Check brake pads and fluid levels",
        "Inspect battery health and clean terminals",
        "Top up coolant, brake, and transmission fluids",
        "Check and replace windshield wipers",
        "Regularly wash and wax the car to prevent rust",
    ]

    checked_tasks = [st.checkbox(task) for task in maintenance_tasks]

    # 2️⃣ Troubleshooting Common Vehicle Issues
    st.subheader("⚠️ Troubleshooting Common Vehicle Issues")
    issues = {
        "Car won’t start": "Check the battery, ignition switch, or fuel system.",
        "Brakes making noise": "Inspect brake pads for wear or replace brake fluid.",
        "Engine overheating": "Check coolant levels and radiator function.",
        "Tires losing pressure frequently": "Check for punctures or valve leaks.",
        "AC not cooling properly": "Clean or replace air filters and check refrigerant levels.",
    }

    selected_issue = st.selectbox("Select a common issue:", list(issues.keys()))
    st.write(f"✅ **Solution:** {issues[selected_issue]}")

    # 3️⃣ Preventive Maintenance Tips
    st.subheader("🔧 Preventive Maintenance Tips")
    st.markdown("""
    - **Follow the manufacturer’s service schedule**: Regular servicing can prevent major breakdowns.
    - **Monitor dashboard warning lights**: Address issues early to avoid costly repairs.
    - **Drive smoothly**: Avoid aggressive driving to reduce wear and tear.
    - **Keep your fuel tank at least half full**: Prevents fuel pump damage.
    - **Store your car in a garage**: Protects it from extreme weather conditions.
    """)

    # 4️⃣ Recommended Service Frequency
    st.subheader("📅 Recommended Service Frequency")
    service_intervals = {
        "Oil & Filter Change": "Every 5,000 - 10,000 km",
        "Brake Inspection": "Every 10,000 - 20,000 km",
        "Tire Rotation & Alignment": "Every 10,000 - 15,000 km",
        "Battery Check": "Every 6 months",
        "Coolant Flush": "Every 40,000 km",
    }

    st.table(service_intervals)

    st.success("🚗 **Stay proactive with maintenance to extend your vehicle’s lifespan!**")
elif page=="Rental Services":
    st.title("🚗 Car Rental Selection & Maintenance Cost Estimator")

    # User selects car type
    st.subheader("🔍 Select Car Type")
    seater_option = st.selectbox("How many seats do you need?", ["4-seater", "5-seater", "7-seater", "SUV", "Luxury"])

    # Sample rental car data (Replace this with your actual data source)
    rental_cars = {
        "4-seater": [
            {"name": "Toyota Corolla", "model": "2022", "price_per_day": "$40"},
            {"name": "Hyundai Elantra", "model": "2021", "price_per_day": "$35"},
        ],
        "5-seater": [
            {"name": "Honda Civic", "model": "2022", "price_per_day": "$45"},
            {"name": "Mazda 3", "model": "2023", "price_per_day": "$50"},
        ],
        "7-seater": [
            {"name": "Toyota Innova", "model": "2022", "price_per_day": "$70"},
            {"name": "Kia Carnival", "model": "2023", "price_per_day": "$85"},
        ],
        "SUV": [
            {"name": "Ford Explorer", "model": "2023", "price_per_day": "$90"},
            {"name": "Chevrolet Tahoe", "model": "2022", "price_per_day": "$100"},
        ],
        "Luxury": [
            {"name": "BMW X5", "model": "2023", "price_per_day": "$150"},
            {"name": "Mercedes-Benz GLE", "model": "2023", "price_per_day": "$180"},
        ],
    }

    # Display available rental cars
    st.subheader(f"🚙 Available {seater_option} Cars")
    cars = rental_cars.get(seater_option, [])
    if cars:
        for car in cars:
            st.markdown(f"**{car['name']} ({car['model']})** - 💰 {car['price_per_day']} per day")
    else:
        st.warning("No cars available for the selected category.")

    # Estimated maintenance costs
    st.subheader("🛠️ Estimated Maintenance Cost")
    maintenance_costs = {
        "4-seater": 5000,
        "5-seater": 7000,
        "7-seater": 10000,
        "SUV": 12000,
        "Luxury": 20000
    }

    cost = maintenance_costs.get(seater_option, 5000)
    st.write(f"💵 **Estimated Annual Maintenance Cost for a {seater_option}:** ${cost}")

    st.success("📌 Choose wisely! Lower maintenance costs can save you money in the long run.")

elif page == "AutoSage Bot":
# Chatbot Page
    st.title("🤖 AutoSage Chatbot")
    st.write("Ask anything about vehicles!")

# Initialize chat history in session state
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

# Display chat history
    for message in st.session_state.chat_history:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

# Chat input
    user_query = st.chat_input("Type your question...")

    if user_query:
    # Display user message
        st.chat_message("user").markdown(user_query)
        st.session_state.chat_history.append({"role": "user", "content": user_query})

    # Get AI response
        with st.spinner("Thinking..."):
            try:
                response = model.generate_content(user_query)
                ai_reply = response.text.strip() if response.text else "I'm not sure about that."

            # Display AI message
                with st.chat_message("assistant"):
                    st.markdown(ai_reply)

            # Store in history
                st.session_state.chat_history.append({"role": "assistant", "content": ai_reply})
            except Exception as e:
                 st.error(f"Error: {str(e)}")


#explorepage
elif page == "Explore":
    st.title("🔍 Explore Vehicles")
    
    col1, col2 = st.columns(2)
    with col1:
        # Vehicle type with callback
        vehicle_type = st.radio(
            "Select Vehicle Type:", 
            ["2-Wheeler", "4-Wheeler"], 
            horizontal=True,
            key="selected_vehicle_type",
            on_change=update_brand_options
        )
        
        # Brand dropdown
        brand = st.selectbox(
            "Select Brand:",
            options=st.session_state.brand_options,
            key="selected_brand"
        )
    
    with col2:
        min_price = st.number_input("Minimum Price ($)", min_value=0, value=20000)
        max_price = st.number_input("Maximum Price ($)", min_value=0, value=100000)
        fuel_type = st.radio("Select Fuel Type:", ["Electric", "Non-Electric"], horizontal=True)

    search_clicked = st.button("Search Vehicles", type="primary")
    
    # Use session state to avoid re-fetching on every rerun
    if "vehicles" not in st.session_state:
        st.session_state.vehicles = []
        st.session_state.has_searched = False
    
    if search_clicked:
        with st.spinner(f"Fetching top {vehicle_type}s based on your criteria..."):
            try:
                st.session_state.vehicles = get_top_vehicles(vehicle_type, brand, min_price, max_price, fuel_type)
                st.session_state.has_searched = True
            except Exception as e:
                st.error(f"Error during search: {str(e)}")
                if "429" in str(e):
                    st.warning("You've hit the API rate limit. Please wait a moment before trying again or try different search criteria.")
    
    if st.session_state.has_searched:
        if st.session_state.vehicles and len(st.session_state.vehicles) > 0:
            st.subheader(f"🚘 Top {len(st.session_state.vehicles)} {fuel_type} {vehicle_type}s")
            
            # Create a dataframe for display
            df = pd.DataFrame(st.session_state.vehicles)
            
            # Add a "Details" column with buttons
            if "selected_vehicle" not in st.session_state:
                st.session_state.selected_vehicle = None
            
            st.table(df)
            
            # Allow user to select a vehicle for more details
            if len(st.session_state.vehicles) > 0:
                selected_index = st.selectbox("Select a vehicle for detailed information:", 
                                             options=range(len(st.session_state.vehicles)),
                                             format_func=lambda i: st.session_state.vehicles[i]["Name"])
                
                if st.button("Show Detailed Specifications"):
                    with st.spinner("Fetching detailed specifications..."):
                        try:
                            vehicle_name = st.session_state.vehicles[selected_index]["Name"]
                            info = get_vehicle_info(vehicle_name)
                            vehicle_data = parse_vehicle_info(info)
                            
                            st.subheader(f"📋 Detailed Specifications for {vehicle_name}")
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                st.metric("Range", vehicle_data["Range"])
                                st.metric("Price", vehicle_data["Price"])
                            
                            with col2:
                                st.metric("Horsepower", vehicle_data["Horsepower"])
                                
                            st.subheader("Features")
                            features = vehicle_data["Features"].split(",")
                            for feature in features:
                                st.write(f"✅ {feature.strip()}")
                            
                           #
                        except Exception as e:
                            st.error(f"Error fetching details: {str(e)}")
                            st.info("Using fallback data instead.")
                            # Provide fallback information
                            vehicle_name = st.session_state.vehicles[selected_index]["Name"]
                            st.subheader(f"📋 Detailed Specifications for {vehicle_name}")
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                st.metric("Range", "300 miles" if fuel_type == "Electric" else "N/A")
                                st.metric("Price", st.session_state.vehicles[selected_index].get("Price", "$45,000"))
                            
                            with col2:
                                st.metric("Horsepower", "250 HP")
                                
                            st.subheader("Features")
                            features = ["Air Conditioning", "Bluetooth", "Navigation", "Cruise Control"]
                            for feature in features:
                                st.write(f"✅ {feature.strip()}")
                            
                            # Add to compare button
                            if st.button("Add to Comparison"):
                                st.session_state.compare_vehicle_1 = vehicle_name
                                st.info(f"Added {vehicle_name} to comparison. Go to Compare page to select a second vehicle.")
        else:
            st.warning("No vehicles found matching your criteria. Try adjusting your filters.")
            
            # Provide suggestions
            st.info("Suggestions: Try widening your price range, selecting 'All Brands', or switching the fuel type.")

elif page == "Compare":
    st.title("⚖️ Compare Vehicles")
    st.subheader("Compare two vehicles side by side.")

    vehicle1 = st.text_input("Enter first vehicle name")
    vehicle2 = st.text_input("Enter second vehicle name")

    if st.button("Compare Now"):
        if vehicle1 and vehicle2:
            try:
                comparison_query = f"Compare {vehicle1} and {vehicle2} in terms of performance, fuel efficiency, and features."
                response = model.generate_content(comparison_query)
                st.subheader(f"🔹 Comparison: {vehicle1} vs {vehicle2}")
                st.write(response.text)
            except Exception as e:
                st.error("⚠️ API request failed. Showing fallback comparison.")
                st.write(f"🚗 {vehicle1} and {vehicle2} are both great choices, but detailed comparison is unavailable at the moment.")

# Footer
st.markdown("---")
st.caption("🚗 AutoSage - AI-Powered Vehicle Analysis | Built with ❤️ using Streamlit & Google Gemini AI")
# Add a footer with app info and reset option
st.sidebar.markdown("---")
if st.sidebar.button("Reset Application"):
    # Clear session state
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.sidebar.success("Application reset! Refresh the page.")

st.sidebar.info("© 2025 AutoSage - AI-Powered Vehicle Comparison Tool")
