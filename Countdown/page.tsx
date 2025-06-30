'use client';
import React, { useState, useEffect, useRef } from 'react';
import { Card, Button, Input } from "@/components/aily";
import dayjs from 'dayjs';

export default function OffWorkCountdown() {
  const [targetTime, setTargetTime] = useState('18:00');
  const [timeLeft, setTimeLeft] = useState({ hours: 0, minutes: 0, seconds: 0 });
  const [history, setHistory] = useState<{date: string, time: string}[]>([]);
  const [showPopup, setShowPopup] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);

  // 计算剩余时间
  const calculateTimeLeft = () => {
    const now = new Date();
    const [targetHours, targetMinutes] = targetTime.split(':').map(Number);
    const targetDate = new Date();
    targetDate.setHours(targetHours, targetMinutes, 0, 0);
    
    // 如果目标时间已过，设置为第二天
    if (now > targetDate) {
      targetDate.setDate(targetDate.getDate() + 1);
    }
    
    const difference = targetDate.getTime() - now.getTime();
    const hours = Math.floor((difference % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
    const minutes = Math.floor((difference % (1000 * 60 * 60)) / (1000 * 60));
    const seconds = Math.floor((difference % (1000 * 60)) / 1000);
    
    return { hours, minutes, seconds };
  };

  // 检查是否下班
  useEffect(() => {
    const timer = setInterval(() => {
      const newTimeLeft = calculateTimeLeft();
      setTimeLeft(newTimeLeft);
      
      // 检查是否到达下班时间
      if (newTimeLeft.hours === 0 && newTimeLeft.minutes === 0 && newTimeLeft.seconds === 0) {
        setShowPopup(true);
        if (audioRef.current) {
          audioRef.current.play();
        }
        
        // 记录下班时间
        const now = new Date();
        const dateStr = dayjs(now).format('YYYY-MM-DD');
        const timeStr = dayjs(now).format('HH:mm:ss');
        setHistory(prev => [...prev, { date: dateStr, time: timeStr }]);
        
        // 10秒后关闭弹窗
        setTimeout(() => setShowPopup(false), 10000);
      }
    }, 1000);
    
    return () => clearInterval(timer);
  }, [targetTime]);

  // 处理时间修改
  const handleTimeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setTargetTime(e.target.value);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-yellow-50 to-orange-50 p-6">
      {/* 下班弹窗 */}
      {showPopup && (
        <div className="fixed inset-0 flex items-center justify-center z-50">
          <div className="animate-fade-in-up bg-gradient-to-r from-yellow-300 to-orange-400 rounded-2xl p-8 shadow-2xl transform animate-pulse">
            <div className="flex flex-col items-center">
              <div className="text-6xl mb-4 animate-spin">🎉</div>
              <h1 className="text-5xl font-bold text-white animate-pulse">下班啦！</h1>
            </div>
          </div>
        </div>
      )}

      {/* 音频元素 */}
      <audio ref={audioRef}>
        <source src="https://www.soundjay.com/misc/sounds/bell-ringing-05.mp3" type="audio/mpeg" />
      </audio>

      <div className="max-w-3xl mx-auto">
        <h1 className="text-4xl font-bold text-center text-orange-500 mb-8">下班倒计时</h1>
        
        {/* 倒计时显示 */}
        <Card className="bg-gradient-to-r from-yellow-100 to-orange-100 shadow-lg">
          <div className="flex justify-center space-x-4">
            <div className="text-center">
              <div className="text-5xl font-bold text-orange-600">{timeLeft.hours.toString().padStart(2, '0')}</div>
              <div className="text-gray-600">小时</div>
            </div>
            <div className="text-5xl font-bold text-orange-500 self-center">:</div>
            <div className="text-center">
              <div className="text-5xl font-bold text-orange-600">{timeLeft.minutes.toString().padStart(2, '0')}</div>
              <div className="text-gray-600">分钟</div>
            </div>
            <div className="text-5xl font-bold text-orange-500 self-center">:</div>
            <div className="text-center">
              <div className="text-5xl font-bold text-orange-600">{timeLeft.seconds.toString().padStart(2, '0')}</div>
              <div className="text-gray-600">秒</div>
            </div>
          </div>
        </Card>

        {/* 下班时间设置 */}
        <Card className="mt-6 bg-gradient-to-r from-yellow-50 to-orange-50">
          <h2 className="text-xl font-semibold text-orange-500 mb-4">设置下班时间</h2>
          <div className="flex items-center space-x-3">
            <Input 
              type="time" 
              value={targetTime} 
              onChange={handleTimeChange}
              className="bg-white border border-orange-200 rounded-lg p-2"
            />
            <Button className="bg-orange-500 hover:bg-orange-600 text-white">
              保存
            </Button>
          </div>
        </Card>

        {/* 下班记录 */}
        <Card className="mt-6 bg-gradient-to-r from-yellow-50 to-orange-50">
          <h2 className="text-xl font-semibold text-orange-500 mb-4">下班记录</h2>
          <div className="max-h-60 overflow-y-auto">
            {history.length === 0 ? (
              <p className="text-gray-500 text-center py-4">还没有下班记录</p>
            ) : (
              <table className="w-full">
                <thead>
                  <tr className="bg-orange-100">
                    <th className="py-2 px-4 text-left">日期</th>
                    <th className="py-2 px-4 text-left">时间</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((record, index) => (
                    <tr key={index} className={index % 2 === 0 ? 'bg-yellow-50' : 'bg-white'}>
                      <td className="py-2 px-4">{record.date}</td>
                      <td className="py-2 px-4">{record.time}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
