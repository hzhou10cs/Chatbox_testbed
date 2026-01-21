%% SMART Dimension Radar (3 benchmarks) from goal-level Excel files
% - Reads 3 Excel files (one per benchmark)
% - Excludes rows with goal_text == 'NONE' (case-insensitive)
% - Computes mean score for each SMART dimension: S/M/A/R/T (0..5)
% - Plots radar chart (same style as your uploaded version)
% MATLAB R2025a

clear; clc;

% -------------------- USER CONFIG --------------------
xlsxFiles  = { ...
    'eval_results\eval_smart_mode0\results_goals.xlsx', ...   % Benchmark A (replace)
    'eval_results\eval_smart_mode1\results_goals.xlsx', ...   % Benchmark B (replace)
    'eval_results\eval_smart_mode2\results_goals.xlsx'  ...   % Benchmark C (replace)
};

benchNames = {'SSC','MSS','SA'};
nBench = numel(xlsxFiles);

sheetName = 1;   % change if needed (e.g., 'Sheet1')
% -----------------------------------------------------

% -------------------- STYLE / COLORS --------------------
fontName = 'Helvetica';
axFontSize = 16;
legFontSize = 16;

lineW = 3;
fillAlpha = 0.10;
gridAlpha = 0.25;

% Benchmark colors (A/B/C)
cBlue   = [0.0353, 0.5176, 0.8902];
cRed    = [0.9098, 0.2549, 0.0941];
cOrange = [0.9294, 0.6941, 0.1255];
colors  = [cRed; cBlue; cOrange];   % A/B/C
% ------------------------------------------------------

% -------------------- DIMENSIONS -----------------------
dimCols = ["specific","measurable","achievable","relevant","time_bound"];
dimShort = {'Specific','Measure','Attainable','Reward','Timeframe'};    % axis tick labels (compact)
nDim = numel(dimCols);
% ------------------------------------------------------

% -------------------- READ + COMPUTE MEANS --------------------
mu = NaN(nBench, nDim);   % benchmark-level means (1x5 per benchmark)
N  = zeros(nBench, 1);    % number of valid goals per benchmark (after NONE filtering)

for b = 1:nBench
    [mu(b,:), N(b)] = compute_dim_means_from_file(xlsxFiles{b}, sheetName, dimCols);
end

% Close polygons for radar
thetaBase = (0:nDim-1)/nDim * 2*pi;
thetaPoly = [thetaBase, thetaBase(1)];
muPoly    = [mu, mu(:,1)];

% -------------------- PLOT (Radar) --------------------
fig = figure('Color','w', 'Position',[100 100 500 400]);

ax = polaraxes(fig, 'Units','normalized', 'Position',[0.08 0.20 0.84 0.75]);
hold(ax,'on');

ax.ThetaZeroLocation = 'top';
ax.ThetaDir = 'clockwise';

ax.RLim  = [0 5];
ax.RTick = 0:1:5;

ax.ThetaTick = rad2deg(thetaBase);
ax.ThetaTickLabel = dimShort;

ax.FontName = fontName;
ax.FontSize = axFontSize;
ax.FontWeight = 'bold';

ax.GridAlpha = gridAlpha;
ax.LineWidth = 1;
ax.Clipping = 'off';

hLine = gobjects(1, nBench);

for b = 1:nBench
    r = muPoly(b,:);

    % Fill (aligned with polar axes): patch(theta,r)
    patch(ax, thetaPoly, r, colors(b,:), ...
        'FaceAlpha', fillAlpha, 'EdgeColor', 'none', 'HandleVisibility','off');

    % Mean polygon line (for legend)
    hLine(b) = polarplot(ax, thetaPoly, r, '-', ...
        'LineWidth', lineW, 'Color', colors(b,:));
end

% Legend: bottom, centered, 1 row
leg = legend(ax, hLine, benchNames, ...
    'Location','southoutside', 'Orientation','horizontal', 'NumColumns', 3);
set(leg, 'Box','on', 'FontName',fontName, 'FontSize',legFontSize, 'FontWeight','bold');

% Force center alignment (robust)
leg.Units = 'normalized';
leg.Position(1) = 0.5 - leg.Position(3)/2;
leg.Position(2) = 0.05;

% Optional: print summary in Command Window
disp('SMART dimension means (excluding goal_text == NONE):');
Tsum = table(string(benchNames(:)), N(:), mu(:,1), mu(:,2), mu(:,3), mu(:,4), mu(:,5), ...
    'VariableNames', {'Benchmark','N_valid_goals','Specific','Measurable','Achievable','Relevant','TimeBound'});
disp(Tsum);

% Optional export
% exportgraphics(fig, 'smart_dimension_radar.png', 'Resolution', 300);
% exportgraphics(fig, 'smart_dimension_radar.pdf', 'ContentType', 'vector');

%% -------------------- LOCAL FUNCTION --------------------
function [muRow, nValid] = compute_dim_means_from_file(xlsxPath, sheetName, dimCols)
%COMPUTE_DIM_MEANS_FROM_FILE Read one goal-level SMART file and compute dimension means.
% Excludes rows where goal_text == 'NONE' (case-insensitive).
% Also drops rows with non-empty parse_error if the column exists.
% Keeps only status_code==200 if the column exists.

    assert(isfile(xlsxPath), 'Excel file not found: %s', xlsxPath);

    T = readtable(xlsxPath, 'Sheet', sheetName, 'VariableNamingRule','preserve');
    vars = string(T.Properties.VariableNames);
    varsLower = lower(vars);

    % Required: goal_text
    iGoal = find(varsLower == "goal_text", 1);
    assert(~isempty(iGoal), 'Missing column "goal_text" in %s', xlsxPath);

    goalText = string(T.(vars(iGoal)));
    goalNorm = lower(strtrim(goalText));

    % Base validity: goal_text not NONE
    valid = ~ismissing(goalNorm) & (goalNorm ~= "none");

    % Optional: status_code == 200
    iStatus = find(varsLower == "status_code", 1);
    if ~isempty(iStatus)
        sc = T.(vars(iStatus));
        valid = valid & ~ismissing(sc) & (sc == 200);
    end

    % Optional: parse_error empty
    iParse = find(varsLower == "parse_error", 1);
    if ~isempty(iParse)
        pe = T.(vars(iParse));
        okParse = true(height(T),1);

        if iscell(pe)
            okParse = cellfun(@(x) isempty(x) || (ischar(x) && isempty(strtrim(x))) || (isstring(x) && strlength(x)==0), pe);
        elseif isstring(pe)
            okParse = ismissing(pe) | (strlength(pe)==0);
        end

        valid = valid & okParse;
    end

    nValid = sum(valid);

    % Compute mean per dimension on valid rows
    muRow = NaN(1, numel(dimCols));

    for k = 1:numel(dimCols)
        iDim = find(varsLower == dimCols(k), 1);
        assert(~isempty(iDim), 'Missing column "%s" in %s', dimCols(k), xlsxPath);

        x = double(T.(vars(iDim)));
        x = x(valid);

        % Safety clamp to [0,5] in case of out-of-range values
        x = min(5, max(0, x));

        muRow(k) = mean(x, 'omitnan');
    end
end
