from database import get_connection, init_db

init_db()
conn = get_connection()

if conn.execute("SELECT COUNT(*) n FROM hotels").fetchone()["n"] == 0:
    hotels = [
        ("StayFlow Grand", "Hyderabad", "A premium city hotel with modern rooms and easy access to business and shopping districts.", "demo_hotel_1.jpg", 4.8),
        ("StayFlow Bay", "Visakhapatnam", "A relaxing waterfront-style property with comfortable rooms and attentive service.", "demo_hotel_2.jpg", 4.7),
        ("StayFlow Residency", "Vijayawada", "A practical and comfortable hotel for business trips, families and short stays.", "demo_hotel_3.jpg", 4.5),
    ]

    for h in hotels:
        conn.execute(
            "INSERT INTO hotels(name,location,description,image,rating) VALUES(?,?,?,?,?)", h
        )

    hotel_ids = [r["id"] for r in conn.execute("SELECT id FROM hotels ORDER BY id").fetchall()]

    rooms = [
        (hotel_ids[0], "101", "Deluxe King", 4200, 1, None, "Wi-Fi, breakfast, AC, TV"),
        (hotel_ids[0], "102", "Executive Suite", 6500, 1, None, "Wi-Fi, breakfast, AC, TV, lounge"),
        (hotel_ids[0], "201", "Twin Deluxe", 4600, 1, None, "Wi-Fi, breakfast, AC, TV"),
        (hotel_ids[1], "301", "Sea View Deluxe", 5200, 1, None, "Wi-Fi, breakfast, AC, balcony"),
        (hotel_ids[1], "302", "Family Room", 6800, 1, None, "Wi-Fi, breakfast, AC, sofa"),
        (hotel_ids[1], "401", "Premium Suite", 7900, 1, None, "Wi-Fi, breakfast, AC, balcony, lounge"),
        (hotel_ids[2], "501", "Standard Queen", 2800, 1, None, "Wi-Fi, AC, TV"),
        (hotel_ids[2], "502", "Deluxe Queen", 3400, 1, None, "Wi-Fi, AC, TV, breakfast"),
        (hotel_ids[2], "503", "Family Deluxe", 4500, 1, None, "Wi-Fi, AC, TV, breakfast, sofa"),
    ]

    conn.executemany("""
        INSERT INTO rooms(hotel_id,room_number,room_type,price,available,image,amenities)
        VALUES(?,?,?,?,?,?,?)
    """, rooms)

    conn.commit()
    print("Demo hotels and rooms created.")
else:
    print("Hotels already exist; no demo data inserted.")

conn.close()