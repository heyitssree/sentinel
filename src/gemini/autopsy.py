"""
Gemini Post-Trade Autopsy Module (Feature C).
Reviews daily trades and provides improvement suggestions.

Features:
- Daily trade analysis with Gemini AI
- Automatic report generation and saving
- Performance metrics tracking
- Improvement suggestions based on trade patterns
- Thinking mode for deep chain-of-thought reasoning
- Opportunity cost analysis (price 2h post-exit)

Upgraded to google-genai SDK with:
- Pydantic structured outputs
- Thinking mode for complex analysis
- System instructions
"""
import os
import json
import time
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from pathlib import Path

from google import genai
from google.genai import types

from .models import AutopsyResponse, ExitTimingVerdict

logger = logging.getLogger(__name__)

# Reports directory
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))


@dataclass
class AutopsyResult:
    """Result of post-trade autopsy."""
    date: datetime
    total_trades: int
    winning_trades: int
    losing_trades: int
    total_pnl: float
    best_trade: Dict
    worst_trade: Dict
    key_observations: List[str]
    stop_loss_suggestion: str
    overall_assessment: str
    improvement_areas: List[str]


class PostTradeAutopsy:
    """
    Reviews daily trades using Gemini with thinking mode for deep analysis.
    Uses google-genai SDK with Pydantic structured outputs.
    """
    
    SYSTEM_INSTRUCTION = """You are an expert trading coach reviewing paper trading activity for Indian stock markets.
Your role is to provide actionable, specific feedback to improve trading performance.

Analysis Framework:
1. Identify patterns in winning vs losing trades
2. Check if exits were too early or too late based on subsequent price action
3. Evaluate entry timing relative to technical signals
4. Assess risk management (stop losses, position sizing)
5. Consider opportunity cost - what happened after exits

Focus on:
- Specific, actionable improvements (not generic advice)
- Quantifiable suggestions (e.g., "Use 1.5x ATR instead of fixed 1%")
- Pattern recognition across multiple trades
- Risk-adjusted performance assessment"""

    def __init__(self, api_key: str = None, model: str = "gemini-2.5-flash"):
        """
        Initialize the autopsy module.
        
        Args:
            api_key: Google Gemini API key (or uses GEMINI_API_KEY env var)
            model: Gemini model to use
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model
        self._setup_client()
        
        self.max_retries = 3
        self.retry_delay = 2.0
        self.use_thinking_mode = True  # Enable deep reasoning
    
    def _setup_client(self):
        """Configure the Gemini client."""
        self.client = genai.Client(api_key=self.api_key)
        logger.info(f"Post-trade autopsy initialized with {self.model_name} (new SDK + thinking mode)")
    
    def _format_trades_summary(self, trades: List[Dict]) -> str:
        """Format trades for the prompt."""
        if not trades:
            return "No trades executed today."
        
        winning = [t for t in trades if t.get('pnl', 0) > 0]
        losing = [t for t in trades if t.get('pnl', 0) <= 0]
        
        avg_win = sum(t['pnl'] for t in winning) / len(winning) if winning else 0
        avg_loss = sum(t['pnl'] for t in losing) / len(losing) if losing else 0
        
        summary = f"""
- Total Trades: {len(trades)}
- Winning Trades: {len(winning)}
- Losing Trades: {len(losing)}
- Win Rate: {len(winning)/len(trades)*100:.1f}%
- Average Win: ₹{avg_win:.2f}
- Average Loss: ₹{avg_loss:.2f}
"""
        return summary
    
    def _format_trade_details(self, trades: List[Dict]) -> str:
        """Format detailed trade log."""
        if not trades:
            return "No trades."
        
        details = []
        for i, trade in enumerate(trades, 1):
            detail = f"""
Trade #{i}: {trade.get('ticker', 'N/A')}
  - Entry: ₹{trade.get('entry_price', 0):.2f} at {trade.get('entry_time', 'N/A')}
  - Exit: ₹{trade.get('exit_price', 0):.2f} at {trade.get('exit_time', 'N/A')}
  - Side: {trade.get('side', 'N/A')}, Qty: {trade.get('quantity', 0)}
  - PnL: ₹{trade.get('pnl', 0):.2f}
  - Entry Reason: {trade.get('entry_reason', 'N/A')}
  - Exit Reason: {trade.get('exit_reason', 'N/A')}
  - Sentiment Score: {trade.get('sentiment_score', 'N/A')}
  - Chart Safety: {trade.get('chart_safety', 'N/A')}
"""
            details.append(detail)
        
        return "\n".join(details)
    
    def _format_tick_summary(self, tick_data: Dict) -> str:
        """Format tick data summary."""
        if not tick_data:
            return "No tick data available."
        
        summaries = []
        for ticker, data in tick_data.items():
            if isinstance(data, dict):
                summary = f"""
{ticker}:
  - Last Price: ₹{data.get('last_price', 0):.2f}
  - Day Range: ₹{data.get('low', 0):.2f} - ₹{data.get('high', 0):.2f}
  - Volume: {data.get('volume', 0):,}
"""
                summaries.append(summary)
        
        return "\n".join(summaries) if summaries else "No tick data available."
    
    def analyze(self, trades: List[Dict], tick_data: Dict = None,
                date: datetime = None, opportunity_cost_data: Dict = None) -> AutopsyResult:
        """
        Perform post-trade autopsy.
        
        Args:
            trades: List of trade dictionaries from database
            tick_data: Optional tick data summary
            date: Trading date (default: today)
            
        Returns:
            AutopsyResult with analysis and suggestions
        """
        date = date or datetime.now()
        
        if not trades:
            return AutopsyResult(
                date=date,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                total_pnl=0.0,
                best_trade={},
                worst_trade={},
                key_observations=["No trades executed today"],
                stop_loss_suggestion="N/A - no trades to analyze",
                overall_assessment="No trading activity to review",
                improvement_areas=[]
            )
        
        # Calculate stats
        total_pnl = sum(t.get('pnl', 0) for t in trades)
        winning = [t for t in trades if t.get('pnl', 0) > 0]
        losing = [t for t in trades if t.get('pnl', 0) <= 0]
        
        best_trade = max(trades, key=lambda x: x.get('pnl', 0)) if trades else {}
        worst_trade = min(trades, key=lambda x: x.get('pnl', 0)) if trades else {}
        
        # Build opportunity cost section if available
        opp_cost_section = ""
        if opportunity_cost_data:
            opp_cost_section = "\n\nOPPORTUNITY COST ANALYSIS (Price 2h after exits):\n"
            for ticker, data in opportunity_cost_data.items():
                exit_price = data.get('exit_price', 0)
                price_2h_later = data.get('price_2h_later', 0)
                change_pct = ((price_2h_later - exit_price) / exit_price * 100) if exit_price > 0 else 0
                opp_cost_section += f"  {ticker}: Exit ₹{exit_price:.2f} → 2h later ₹{price_2h_later:.2f} ({change_pct:+.2f}%)\n"
        
        # Prepare prompt
        prompt = f"""Review this day's paper trading activity and provide detailed analysis.

DATE: {date.strftime("%Y-%m-%d")}
TOTAL PNL: ₹{total_pnl:.2f}

TRADES SUMMARY:
{self._format_trades_summary(trades)}

DETAILED TRADE LOG:
{self._format_trade_details(trades)}

TICK DATA SUMMARY (Last hour):
{self._format_tick_summary(tick_data or {})}{opp_cost_section}

Provide your analysis with specific, actionable feedback."""
        
        # Call Gemini with thinking mode for deep analysis
        for attempt in range(self.max_retries):
            try:
                # Configure thinking mode for complex reasoning
                config = types.GenerateContentConfig(
                    system_instruction=self.SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=AutopsyResponse,
                )
                
                # Enable thinking mode if available (Gemini 2.5+)
                if self.use_thinking_mode:
                    config.thinking_config = types.ThinkingConfig(
                        thinking_budget=1024  # Allow deep reasoning
                    )
                
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config
                )
                
                # Parse structured response
                result = AutopsyResponse.model_validate_json(response.text)
                
                return AutopsyResult(
                    date=date,
                    total_trades=len(trades),
                    winning_trades=len(winning),
                    losing_trades=len(losing),
                    total_pnl=total_pnl,
                    best_trade=best_trade,
                    worst_trade=worst_trade,
                    key_observations=result.key_observations,
                    stop_loss_suggestion=result.stop_loss_suggestion,
                    overall_assessment=result.overall_assessment,
                    improvement_areas=result.improvement_areas
                )
                
            except Exception as e:
                logger.warning(f"Autopsy attempt {attempt+1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
        
        # Return basic result on failure
        return AutopsyResult(
            date=date,
            total_trades=len(trades),
            winning_trades=len(winning),
            losing_trades=len(losing),
            total_pnl=total_pnl,
            best_trade=best_trade,
            worst_trade=worst_trade,
            key_observations=["Gemini analysis failed"],
            stop_loss_suggestion="Analysis unavailable",
            overall_assessment=f"Day ended with ₹{total_pnl:.2f} PnL",
            improvement_areas=[]
        )
    
    def format_report(self, result: AutopsyResult) -> str:
        """Format autopsy result as readable report."""
        report = f"""
╔══════════════════════════════════════════════════════════════════╗
║              THE SENTINEL - POST-TRADE AUTOPSY                    ║
║                    {result.date.strftime('%Y-%m-%d')}                               ║
╚══════════════════════════════════════════════════════════════════╝

📊 DAILY SUMMARY
────────────────────────────────────────────────────────────────────
  Total Trades:    {result.total_trades}
  Winning Trades:  {result.winning_trades} ({(result.winning_trades/result.total_trades*100) if result.total_trades > 0 else 0:.1f}% win rate)
  Losing Trades:   {result.losing_trades}
  Total PnL:       ₹{result.total_pnl:,.2f}

💡 KEY OBSERVATIONS
────────────────────────────────────────────────────────────────────
"""
        for i, obs in enumerate(result.key_observations, 1):
            report += f"  {i}. {obs}\n"
        
        report += f"""
🎯 STOP-LOSS RECOMMENDATION
────────────────────────────────────────────────────────────────────
  {result.stop_loss_suggestion}

📈 OVERALL ASSESSMENT
────────────────────────────────────────────────────────────────────
  {result.overall_assessment}

🔧 AREAS FOR IMPROVEMENT
────────────────────────────────────────────────────────────────────
"""
        for area in result.improvement_areas:
            report += f"  • {area}\n"
        
        if result.best_trade:
            report += f"""
🏆 BEST TRADE: {result.best_trade.get('ticker', 'N/A')} | PnL: ₹{result.best_trade.get('pnl', 0):.2f}
"""
        
        if result.worst_trade:
            report += f"""
📉 WORST TRADE: {result.worst_trade.get('ticker', 'N/A')} | PnL: ₹{result.worst_trade.get('pnl', 0):.2f}
"""
        
        return report
    
    def save_report(self, result: AutopsyResult, report_text: str = None) -> str:
        """
        Save autopsy report to file.
        
        Args:
            result: AutopsyResult to save
            report_text: Optional pre-formatted report text
            
        Returns:
            Path to saved report file
        """
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        
        date_str = result.date.strftime("%Y-%m-%d")
        report_file = REPORTS_DIR / f"autopsy_{date_str}.txt"
        json_file = REPORTS_DIR / f"autopsy_{date_str}.json"
        
        # Save text report
        report_text = report_text or self.format_report(result)
        report_file.write_text(report_text)
        
        # Save JSON data for analysis
        json_data = {
            "date": date_str,
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "win_rate": result.winning_trades / result.total_trades * 100 if result.total_trades > 0 else 0,
            "total_pnl": result.total_pnl,
            "best_trade": result.best_trade,
            "worst_trade": result.worst_trade,
            "key_observations": result.key_observations,
            "stop_loss_suggestion": result.stop_loss_suggestion,
            "overall_assessment": result.overall_assessment,
            "improvement_areas": result.improvement_areas,
            "generated_at": datetime.now().isoformat()
        }
        json_file.write_text(json.dumps(json_data, indent=2, default=str))
        
        logger.info(f"Autopsy report saved: {report_file}")
        return str(report_file)
    
    def generate_daily_report(self, db, date: datetime = None) -> AutopsyResult:
        """
        Generate daily autopsy report from database.
        
        Args:
            db: SentinelDB instance
            date: Date to generate report for (default: today)
            
        Returns:
            AutopsyResult with analysis
        """
        date = date or datetime.now()
        
        # Get today's trades from database
        trades_df = db.get_todays_trades()
        
        if trades_df.empty:
            logger.info("No trades today, generating empty report")
            result = AutopsyResult(
                date=date,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                total_pnl=0.0,
                best_trade={},
                worst_trade={},
                key_observations=["No trades executed today"],
                stop_loss_suggestion="N/A",
                overall_assessment="No trading activity",
                improvement_areas=[]
            )
        else:
            # Convert DataFrame to list of dicts
            trades = trades_df.to_dict('records')
            
            # Get tick data for context
            tick_data = {}
            for ticker in set(t.get('ticker') for t in trades if t.get('ticker')):
                latest = db.get_latest_candle(ticker)
                if latest:
                    tick_data[ticker] = latest
            
            # Run analysis
            result = self.analyze(trades, tick_data, date)
        
        # Save report
        report_text = self.format_report(result)
        self.save_report(result, report_text)
        
        return result
    
    def generate_daily_markdown(self, db, date: datetime = None) -> str:
        """
        Generate daily autopsy report as Markdown for in-app display.
        
        Args:
            db: SentinelDB instance
            date: Date to generate report for (default: today)
            
        Returns:
            Markdown-formatted report string for frontend rendering
        """
        date = date or datetime.now()
        
        # Get today's trades from database
        trades_df = db.get_todays_trades()
        
        if trades_df.empty:
            return self._empty_markdown_report(date)
        
        # Convert DataFrame to list of dicts
        trades = trades_df.to_dict('records')
        
        # Get tick data for context
        tick_data = {}
        for ticker in set(t.get('ticker') for t in trades if t.get('ticker')):
            latest = db.get_latest_candle(ticker)
            if latest:
                tick_data[ticker] = latest
        
        # Run analysis
        result = self.analyze(trades, tick_data, date)
        
        return self._format_markdown_report(result)
    
    def _empty_markdown_report(self, date: datetime) -> str:
        """Generate empty report markdown."""
        return f"""# 📊 Daily Autopsy Report

**Date:** {date.strftime('%A, %B %d, %Y')}

---

## Summary

No trades were executed today. The trading engine was either in observation mode or no signals met the confluence criteria.

---

## Tomorrow's Focus

- Review market conditions at open
- Check for any overnight news that may affect watchlist stocks
- Ensure historical data is properly bootstrapped for 200 EMA calculation
"""
    
    def _format_markdown_report(self, result: AutopsyResult) -> str:
        """Format AutopsyResult as Markdown for frontend display."""
        # Determine emoji based on P&L
        pnl_emoji = "🟢" if result.total_pnl >= 0 else "🔴"
        pnl_status = "Profitable" if result.total_pnl >= 0 else "Loss"
        
        # Calculate win rate
        win_rate = (result.winning_trades / result.total_trades * 100) if result.total_trades > 0 else 0
        
        md = f"""# 📊 Daily Autopsy Report

**Date:** {result.date.strftime('%A, %B %d, %Y')}

---

## {pnl_emoji} Performance Summary

| Metric | Value |
|--------|-------|
| **Total P&L** | ₹{result.total_pnl:,.2f} ({pnl_status}) |
| **Total Trades** | {result.total_trades} |
| **Winning Trades** | {result.winning_trades} |
| **Losing Trades** | {result.losing_trades} |
| **Win Rate** | {win_rate:.1f}% |

---

## 💡 Key Observations

"""
        # Add observations as bullet points
        for obs in result.key_observations:
            md += f"- {obs}\n"
        
        md += f"""
---

## 🎯 Overall Assessment

> {result.overall_assessment}

---

## 🛡️ Stop-Loss Recommendation

{result.stop_loss_suggestion}

---

## 🔧 Areas for Improvement

"""
        # Add improvement areas
        if result.improvement_areas:
            for area in result.improvement_areas:
                md += f"1. {area}\n"
        else:
            md += "_No specific improvements identified._\n"
        
        # Best and worst trades
        md += "\n---\n\n## 📈 Trade Highlights\n\n"
        
        if result.best_trade:
            best_pnl = result.best_trade.get('pnl', 0)
            best_ticker = result.best_trade.get('ticker', 'N/A')
            best_entry = result.best_trade.get('entry_price', 0)
            best_exit = result.best_trade.get('exit_price', 0)
            md += f"""### 🏆 Best Trade

**{best_ticker}** — P&L: ₹{best_pnl:,.2f}

- Entry: ₹{best_entry:,.2f}
- Exit: ₹{best_exit:,.2f}
- Reason: {result.best_trade.get('entry_reason', 'N/A')}

"""
        
        if result.worst_trade:
            worst_pnl = result.worst_trade.get('pnl', 0)
            worst_ticker = result.worst_trade.get('ticker', 'N/A')
            worst_entry = result.worst_trade.get('entry_price', 0)
            worst_exit = result.worst_trade.get('exit_price', 0)
            md += f"""### 📉 Worst Trade

**{worst_ticker}** — P&L: ₹{worst_pnl:,.2f}

- Entry: ₹{worst_entry:,.2f}
- Exit: ₹{worst_exit:,.2f}
- Reason: {result.worst_trade.get('exit_reason', 'N/A')}

"""
        
        # Footer
        md += f"""---

*Report generated at {datetime.now().strftime('%H:%M:%S')} IST by The Sentinel AI*
"""
        
        return md
    
    def get_cached_markdown(self, date: datetime = None) -> Optional[str]:
        """
        Get cached markdown report if available.
        
        Args:
            date: Date to get report for (default: today)
            
        Returns:
            Markdown string if cached report exists, None otherwise
        """
        date = date or datetime.now()
        date_str = date.strftime("%Y-%m-%d")
        json_file = REPORTS_DIR / f"autopsy_{date_str}.json"
        
        if not json_file.exists():
            return None
        
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
            
            # Reconstruct AutopsyResult from cached data
            result = AutopsyResult(
                date=datetime.strptime(data['date'], "%Y-%m-%d"),
                total_trades=data['total_trades'],
                winning_trades=data['winning_trades'],
                losing_trades=data['losing_trades'],
                total_pnl=data['total_pnl'],
                best_trade=data.get('best_trade', {}),
                worst_trade=data.get('worst_trade', {}),
                key_observations=data.get('key_observations', []),
                stop_loss_suggestion=data.get('stop_loss_suggestion', ''),
                overall_assessment=data.get('overall_assessment', ''),
                improvement_areas=data.get('improvement_areas', [])
            )
            
            return self._format_markdown_report(result)
            
        except Exception as e:
            logger.warning(f"Failed to load cached report: {e}")
            return None


class DailyReportGenerator:
    """
    Scheduled daily report generator.
    Call this during POST_MARKET phase.
    """
    
    def __init__(self, autopsy: PostTradeAutopsy, db):
        self.autopsy = autopsy
        self.db = db
        self._last_report_date: Optional[datetime] = None
    
    def should_generate(self) -> bool:
        """Check if report should be generated today."""
        today = datetime.now().date()
        if self._last_report_date and self._last_report_date.date() == today:
            return False
        return True
    
    def generate(self) -> Optional[AutopsyResult]:
        """Generate report if not already done today."""
        if not self.should_generate():
            logger.info("Report already generated today")
            return None
        
        result = self.autopsy.generate_daily_report(self.db)
        self._last_report_date = datetime.now()
        
        logger.info(f"Daily report generated: {result.total_trades} trades, ₹{result.total_pnl:.2f} PnL")
        return result


class MockPostTradeAutopsy:
    """Mock autopsy for testing."""
    
    def __init__(self):
        logger.info("Mock post-trade autopsy initialized")
    
    def analyze(self, trades: List[Dict], tick_data: Dict = None,
                date: datetime = None, opportunity_cost_data: Dict = None) -> AutopsyResult:
        """Return mock autopsy result."""
        date = date or datetime.now()
        total_pnl = sum(t.get('pnl', 0) for t in trades) if trades else 0
        winning = [t for t in trades if t.get('pnl', 0) > 0] if trades else []
        losing = [t for t in trades if t.get('pnl', 0) <= 0] if trades else []
        
        return AutopsyResult(
            date=date,
            total_trades=len(trades) if trades else 0,
            winning_trades=len(winning),
            losing_trades=len(losing),
            total_pnl=total_pnl,
            best_trade=max(trades, key=lambda x: x.get('pnl', 0)) if trades else {},
            worst_trade=min(trades, key=lambda x: x.get('pnl', 0)) if trades else {},
            key_observations=[
                "Mock observation: Entry timing was good on winning trades",
                "Mock observation: Stop losses were hit on 2 trades",
            ],
            stop_loss_suggestion="Consider using 1.5x ATR instead of fixed percentage",
            overall_assessment=f"Mock analysis: Day ended with ₹{total_pnl:.2f}",
            improvement_areas=["Entry timing", "Position sizing"]
        )
    
    def format_report(self, result: AutopsyResult) -> str:
        """Format mock report."""
        return PostTradeAutopsy.format_report(self, result)
