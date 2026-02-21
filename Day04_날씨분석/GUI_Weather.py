import requests
import tkinter as tk
from tkinter import font
from PIL import ImageTk

def test_function(entry):
    print("button clicked :", entry)

def get_weather(city):
    weather_key = "개인 API Key 사용"
    url = 'https://api.openweathermap.org/data/2.5/weather'
    params = {'APPID':weather_key,'q':city,'units':'metric','lang':'kr'} 
    res = requests.get(url, params=params)
    weather = res.json()
    label['text'] = format_response(weather)
    # print(weather)

def format_response(weather):
    try:
        name = weather['name']
        desc = weather['weather'][0]['description']
        temp = weather['main']['temp']
        temp_min = weather['main']['temp_min']
        temp_max = weather['main']['temp_max']
        humidity = weather['main']['humidity']
        wind_speed = weather['wind']['speed']

        final_str = f'도시: {name}\n날씨: {desc}\n온도: {temp}°C\n최저온도: {temp_min}°C\n최고온도: {temp_max}°C\n습도: {humidity}%\n풍속: {wind_speed}m/s'

    except:
        final_str = "오류가 있습니다. 확인해주세요."

    return final_str

root = tk.Tk()

canvas = tk.Canvas(root, height=500, width =700)
canvas.pack()

background_image = ImageTk.PhotoImage(file='Day4/weather.jpg')  # 상대경로 사용 
background_label = tk.Label(root, image=background_image)
background_label.place(x = 0, y = 0, relwidth = 1, relheight = 1)

frame = tk.Frame(root,bg='blue',bd=5)
frame.place(relx=0.5, rely=0.1, relwidth=0.75, relheight=0.1, anchor='n')

button = tk.Button(frame, text ='Search',font=40, command=lambda: get_weather(entry.get()))
button.place(relx=0.7, relwidth=0.3, relheight=1)

entry = tk.Entry(frame, font=40)
entry.place(relwidth=0.65, relheight=1)

lower_frame = tk.Frame(root, bg='blue',bd=10)
lower_frame.place(relx=0.5, rely=0.25, relwidth=0.75,relheight=0.6, anchor='n')

label = tk.Label(lower_frame, font=("휴먼매직체",18) )
label.place( relwidth=1, relheight=1)

root.mainloop()