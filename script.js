async function fetchBitcoinData() {
    const response = await fetch('https://api.upbit.com/v1/candles/days?market=KRW-BTC&count=37'); // 7일 추가 데이터
    const data = await response.json();
    return data.reverse().map(d => ({
        x: new Date(d.candle_date_time_kst),
        y: [d.opening_price, d.high_price, d.low_price, d.trade_price],
        label: d.candle_date_time_kst
    }));
}

function calculateMovingAverage(data, count) {
    let result = [];
    for (let i = 0; i <= data.length - count; i++) {
        let sum = 0;
        for (let j = 0; j < count; j++) {
            sum += data[i + j].y[3]; // 종가 기준
        }
        let average = sum / count;
        result.push({
            x: data[i + count - 1].x,
            y: average
        });
    }
    return result;
}

async function drawChart() {
    const bitcoinData = await fetchBitcoinData();
    const movingAverageData = calculateMovingAverage(bitcoinData, 7);
    
    const chart = new CanvasJS.Chart("chartContainer", {
        animationEnabled: true,
        exportEnabled: true,
        theme: "light2",
        title: {
            text: "비트코인 30일 추이 및 7일 평균선"
        },
        axisX: {
            valueFormatString: "DD MMM"
        },
        axisY: {
            prefix: "₩",
            title: "가격 (KRW)"
        },
        toolTip: {
            shared: true,
            contentFormatter: function (e) {
                var content = " ";
                for (var i = 0; i < e.entries.length; i++) {
                    content += e.entries[i].dataSeries.name + ": " + "₩" + e.entries[i].dataPoint.y;
                    if (i < e.entries.length - 1) content += "<br/>";
                }
                return content;
            }
        },
        data: [{
            type: "candlestick",
            name: "비트코인 가격",
            showInLegend: true,
            yValueFormatString: "₩###,###.##",
            xValueFormatString: "DD MMM, YYYY",
            dataPoints: bitcoinData.slice(-30) // 최근 30일만 표시
        },
        {
            type: "line",
            name: "7일 평균선",
            showInLegend: true,
            yValueFormatString: "₩###,###.##",
            dataPoints: movingAverageData
        }]
    });
    chart.render();
}

drawChart();
